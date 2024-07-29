from tkinter import *
import os
root = Tk()
root.geometry("200x300")
root.title(" Q&A ")
l6 = Label(text = "d")
def Take_input():
	INPUT = inputtxt.get("1.0", "end-1c")
	print(INPUT)
	if(INPUT == "1"):
		os.system("python D:\yolov5d-20240319T194141Z-001\yolov5d\detect.py --weights best.pt --source 0")
		#Output.insert(END, 'Correct')
		Output.insert(END,"Modek ")
	elif(INPUT == "2"):
		os.system("python D:\yolov5d-20240319T194141Z-001\yolov5d\detect.py --weights yolov5s.pt --source 0")
		Output.insert(END,"Modek ")
		#Output.insert(END, "Wrong answer")
	elif(INPUT == "2"):
		os.system("dd")
		Output.insert(END,"Modek ")
	elif(INPUT == "3"):
		os.system("dd")
		Output.insert(END,"Modek ")
	elif(INPUT == "4"):
		os.system("dd")
		Output.insert(END,"Modek ")
	elif(INPUT == "5"):
		os.system("dd")
		Output.insert(END,"Modek ")
	else:
		Output.insert(END,"Wrong Enter")
		

	
l1 = Label(text = "yolov5 press =1 ")
l2 = Label(text = "modeu1 ")
l3 = Label(text = "modeu1 ")
l4 = Label(text = "modeu1 ")
l5 = Label(text = "modeu1 ")


inputtxt = Text(root, height = 2,width = 5,bg = "light yellow")
'''
python D:\Phd\yolo\yolov5-master\yolov5-master\detect.py --weights D:\Phd\yolo\yolov5-master\yolov5-master\best.pt --source 0
'''
Output = Text(root, height = 2,width = 5,bg = "light cyan")
"""
Display = Button(root, height = 2,width = 20,text ="Show",command = lambda:Take_input())
"""
Display = Button(root, height = 2,width = 5, 
				text ="RUN",command = lambda:Take_input())
Displayy = Button(root, height = 2,width = 5, 
				text ="Exit",command = lambda:root.quit())

root.title("Image Display in Tkinter") # Change this Label

# Load the image
image = PhotoImage(file="1.png")

# Create a label to display the image
image_label =Label(root, image=image, width=100, height=100)

image_label.pack()
l1.pack()
l2.pack()
l3.pack()
l4.pack()
l5.pack()
l6.pack()
inputtxt.pack()
Display.pack()
Displayy.pack()
Output.pack()

mainloop()
