import torch
import math
import torch.nn.functional as F
from torch import nn, Tensor


class MLP(nn.Module):
    def __init__(self, dim, hidden_dim, out_dim=None) -> None:
        super().__init__()
        out_dim = out_dim or dim
        self.fc1 = nn.Linear(dim, hidden_dim)
        self.act = nn.GELU()
        self.fc2 = nn.Linear(hidden_dim, out_dim)

    def forward(self, x: Tensor) -> Tensor:
        return self.fc2(self.act(self.fc1(x)))


class PositionalEncodingFourier(nn.Module):
    def __init__(self, dim: int = 768):
        super().__init__()
        self.dim = dim
        self.hidden_dim = 32
        self.token_projection = nn.Conv2d(self.hidden_dim * 2, dim, 1)
        self.scale = 2 * math.pi

    def forward(self, B: int, H: int, W: int) -> Tensor:
        mask = torch.zeros(B, H, W).bool().to(self.token_projection.weight.device)
        not_mask = ~mask
        y_embed = not_mask.cumsum(1, dtype=torch.float32)
        x_embed = not_mask.cumsum(2, dtype=torch.float32)
        y_embed = y_embed / (y_embed[:, -1:, :] + 1e-6) * self.scale
        x_embed = x_embed / (x_embed[:, :, -1:] + 1e-6) * self.scale

        dim_t = torch.arange(self.hidden_dim, dtype=torch.float32, device=mask.device)
        dim_t = 10000 ** (2 * (torch.div(dim_t, 2, rounding_mode='floor')) / self.hidden_dim)

        pos_x = x_embed[:, :, :, None] / dim_t
        pos_y = y_embed[:, :, :, None] / dim_t

        pos_x = torch.stack((pos_x[:, :, :, 0::2].sin(),
                             pos_x[:, :, :, 1::2].cos()), dim=4).flatten(3)
        pos_y = torch.stack((pos_y[:, :, :, 0::2].sin(),
                             pos_y[:, :, :, 1::2].cos()), dim=4).flatten(3)
        pos = torch.cat((pos_y, pos_x), dim=3).permute(0, 3, 1, 2)
        pos = self.token_projection(pos)
        return pos


class Conv3x3(nn.Sequential):
    def __init__(self, c1, c2, s=1):
        super().__init__(
            nn.Conv2d(c1, c2, 3, s, 1, bias=False),
            nn.BatchNorm2d(c2)
        )


class ConvPatchEmbed(nn.Module):
    """Image to Patch Embedding using multiple convolutional layers
    """
    def __init__(self, patch_size=8, embed_dim=768):
        super().__init__()
        if patch_size == 16:
            self.proj = nn.Sequential(
                Conv3x3(3, embed_dim // 8, 2),
                nn.GELU(),
                Conv3x3(embed_dim // 8, embed_dim // 4, 2),
                nn.GELU(),
                Conv3x3(embed_dim // 4, embed_dim // 2, 2),
                nn.GELU(),
                Conv3x3(embed_dim // 2, embed_dim, 2),
            )
        else:
            self.proj = nn.Sequential(
                Conv3x3(3, embed_dim // 4, 2),
                nn.GELU(),
                Conv3x3(embed_dim // 4, embed_dim // 2, 2),
                nn.GELU(),
                Conv3x3(embed_dim // 2, embed_dim, 2),
            )

    def forward(self, x: Tensor):
        x = self.proj(x)
        _, _, H, W = x.shape
        x = x.flatten(2).transpose(1, 2)
        return x, (H, W)


class LPI(nn.Module):
    """
    Local Patch Interaction module that allows explicit communication between tokens in 3x3 windows
    to augment the implicit communcation performed by the block diagonal scatter attention.
    Implemented using 2 layers of separable 3x3 convolutions with GeLU and BatchNorm2d
    """
    def __init__(self, dim: int):
        super().__init__()
        self.conv1 = nn.Conv2d(dim, dim, 3, 1, 1, groups=dim)
        self.act = nn.GELU()
        self.bn = nn.BatchNorm2d(dim)
        self.conv2 = nn.Conv2d(dim, dim, 3, 1, 1, groups=dim)

    def forward(self, x: Tensor, H: int, W: int) -> Tensor:
        B, N, C = x.shape
        x = x.permute(0, 2, 1).reshape(B, C, H, W)
        x = self.conv2(self.bn(self.act(self.conv1(x))))
        x = x.reshape(B, C, N).permute(0, 2, 1)
        return x


class ClassAttention(nn.Module):
    """ClassAttention as in CaiT
    """
    def __init__(self, dim: int, heads: int):
        super().__init__()
        self.num_heads = heads
        self.scale = (dim // heads) ** -0.5

        self.qkv = nn.Linear(dim, dim * 3)
        self.proj = nn.Linear(dim, dim)

    def forward(self, x: Tensor) -> Tensor:
        B, N, C = x.shape
        qkv = self.qkv(x).reshape(B, N, 3, self.num_heads, C // self.num_heads).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]

        qc = q[:, :, 0:1]  # CLS token

        attn_cls = (qc * k).sum(dim=-1) * self.scale
        attn_cls = attn_cls.softmax(dim=-1)

        cls_token = (attn_cls.unsqueeze(2) @ v).transpose(1, 2).reshape(B, 1, C)
        cls_token = self.proj(cls_token)

        x = torch.cat([cls_token, x[:, 1:]], dim=1)
        return x


class XCA(nn.Module):
    """ Cross-Covariance Attention (XCA) operation where the channels are updated using a weighted
     sum. The weights are obtained from the (softmax normalized) Cross-covariance
    matrix (Q^T K \\in d_h \\times d_h)
    """
    def __init__(self, dim: int, heads: int):
        super().__init__()
        self.num_heads = heads
        self.temperature = nn.Parameter(torch.ones(heads, 1, 1))

        self.qkv = nn.Linear(dim, dim * 3)
        self.proj = nn.Linear(dim, dim)

    def forward(self, x: Tensor) -> Tensor:
        B, N, C = x.shape
        qkv = self.qkv(x).reshape(B, N, 3, self.num_heads, C // self.num_heads).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0].transpose(-2, -1), qkv[1].transpose(-2, -1), qkv[2].transpose(-2, -1)
        q = F.normalize(q, dim=-1)
        k = F.normalize(k, dim=-1)
        attn = (q @ k.transpose(-2, -1)) * self.temperature
        attn = attn.softmax(dim=-1)

        x = (attn @ v).permute(0, 3, 1, 2).reshape(B, N, C)
        x = self.proj(x)
        return x


class ClassAttentionBlock(nn.Module):
    def __init__(self, dim, heads, eta=1e-5):
        super().__init__()
        self.norm1 = nn.LayerNorm(dim)
        self.attn = ClassAttention(dim, heads)
        self.norm2 = nn.LayerNorm(dim)
        self.mlp = MLP(dim, int(dim * 4))

        self.gamma1 = nn.Parameter(eta * torch.ones(dim))
        self.gamma2 = nn.Parameter(eta * torch.ones(dim))

    def forward(self, x: Tensor) -> Tensor:
        x = x + (self.gamma1 * self.attn(self.norm1(x)))
        x = self.norm2(x)

        x_res = x
        cls_token = self.gamma2 * self.mlp(x[:, :1])
        x = torch.cat([cls_token, x[:, 1:]], dim=1)
        x += x_res
        return x


class XCABlock(nn.Module):
    def __init__(self, dim, heads, eta=1e-5):
        super().__init__()
        self.norm1 = nn.LayerNorm(dim)
        self.attn = XCA(dim, heads)
        self.norm2 = nn.LayerNorm(dim)
        self.mlp = MLP(dim, int(dim * 4))
        self.norm3 = nn.LayerNorm(dim)
        self.local_mp = LPI(dim)

        self.gamma1 = nn.Parameter(eta * torch.ones(dim))
        self.gamma2 = nn.Parameter(eta * torch.ones(dim))
        self.gamma3 = nn.Parameter(eta * torch.ones(dim))

    def forward(self, x: Tensor, H, W) -> Tensor:
        x = x + self.gamma1 * self.attn(self.norm1(x))
        x = x + self.gamma3 * self.local_mp(self.norm3(x), H, W)
        x = x + self.gamma2 * self.mlp(self.norm2(x))
        return x


xcit_settings = {   
    'S12/8': [8, 12, 384, 8], #[patch_size, layers, embed dim, heads]
    'S12/16': [16, 12, 384, 8],
    'M24/16': [16, 24, 512, 8],
}


class XciT(nn.Module):
    def __init__(self, model_name: str = 'S12/8', *args, **kwargs) -> None:
        super().__init__()
        assert model_name in xcit_settings.keys(), f"XciT model name should be in {list(xcit_settings.keys())}"
        patch_size, layers, embed_dim, heads = xcit_settings[model_name]
        
        self.patch_embed = ConvPatchEmbed(patch_size, embed_dim)
        self.cls_token = nn.Parameter(torch.zeros(1, 1, embed_dim))

        self.pos_embeder = PositionalEncodingFourier(dim=embed_dim)

        self.blocks = nn.ModuleList([
            XCABlock(embed_dim, heads)
        for _ in range(layers)])

        self.cls_attn_blocks = nn.ModuleList([
            ClassAttentionBlock(embed_dim, heads)
        for _ in range(2)])
        self.norm = nn.LayerNorm(embed_dim)

    def encode_image(self, x):
        return self.forward(x)
        
    def forward(self, x):
        B = x.shape[0]
        x, (Hp, Wp) = self.patch_embed(x)   
        x += self.pos_embeder(B, Hp, Wp).reshape(B, -1, x.shape[1]).permute(0, 2, 1)  

        for blk in self.blocks:
            x = blk(x, Hp, Wp)

        cls_tokens = self.cls_token.expand(B, -1, -1)
        x = torch.cat((cls_tokens, x), dim=1)

        for blk in self.cls_attn_blocks:
            x = blk(x)

        x = self.norm(x)
        return x[:, 0]


if __name__ == '__main__':
    model = XciT('S12/16')
    model.load_state_dict(torch.load('checkpoints/xcit/dino_xcit_small_12_p16_pretrain.pth', map_location='cpu'))
    x = torch.zeros(1, 3, 224, 224)
    y = model(x)
    print(y.shape)
