"""Generate the two original, deterministic illustrations used by the example."""
from pathlib import Path
import math
from PIL import Image, ImageDraw, ImageFont

OUT=Path(__file__).resolve().parents[1]/'src/visual_latex_editor/example/assets'
OUT.mkdir(parents=True,exist_ok=True)

def font(size):
    return ImageFont.load_default(size=size)

im=Image.new('RGB',(1100,540),'#f3f1e8')
d=ImageDraw.Draw(im)
d.rounded_rectangle((35,35,1065,505),radius=24,fill='#fbfaf6',outline='#dfe2d5',width=2)
d.ellipse((120,362,557,425),fill='#d6ddd0')
d.ellipse((448,195,580,330),fill='#668e7c')
d.ellipse((477,218,555,307),fill='#fbfaf6')
d.rounded_rectangle((173,189,490,382),radius=52,fill='#7ca18c')
d.ellipse((173,155,490,228),fill='#d6e2d3')
d.ellipse((193,172,470,215),fill='#a87a41')
for x in (258,330,400):
    d.line([(x,128),(x-18,111),(x-20,84),(x-3,63)],fill='#becab7',width=6,joint='curve')
d.rounded_rectangle((650,104,1005,401),radius=18,fill='#edf2e8')
d.text((682,136),'A CUP OF TEA',font=font(28),fill='#426955')
d.text((682,205),'Start: 85 C',font=font(27),fill='#56745d')
d.text((682,259),'Room: 22 C',font=font(27),fill='#56745d')
d.text((682,335),'Observe. Edit. Repeat.',font=font(18),fill='#8a9a80')
im.save(OUT/'tea-cup.png')

im=Image.new('RGB',(1200,660),'#fbfaf6')
d=ImageDraw.Draw(im)
left,top,right,bottom=120,95,1130,530
xy=lambda t,temp:(left+(right-left)*t/20,bottom-(bottom-top)*(temp-20)/70)
d.text((120,27),'Tea cooling over time',font=font(32),fill='#345d4d')
for temp in (20,40,60,80):
    y=xy(0,temp)[1]
    d.line((left,y,right,y),fill='#e0e5d9',width=2)
    d.text((52,y-13),str(temp),font=font(23),fill='#7c8872')
for t in (0,5,10,15,20):
    x=xy(t,20)[0]
    d.line((x,top,x,bottom),fill='#eff1e8',width=2)
    d.text((x-10,bottom+20),str(t),font=font(23),fill='#7c8872')
d.line((left,top,left,bottom,right,bottom),fill='#94a18b',width=3)
y=xy(0,22)[1]
for x in range(left,right,23):
    d.line((x,y,min(x+12,right),y),fill='#bc9263',width=3)
d.text((820,y-38),'Room temperature: 22 C',font=font(19),fill='#aa8051')
points=[xy(t/10,22+63*math.exp(-(t/10)/8)) for t in range(201)]
d.line(points,fill='#377961',width=6,joint='curve')
for t in (0,5,10,15,20):
    x,y=xy(t,22+63*math.exp(-t/8))
    d.ellipse((x-8,y-8,x+8,y+8),fill='#377961',outline='#fbfaf6',width=2)
d.text((465,603),'Time (minutes)',font=font(24),fill='#62775c')
d.text((125,68),'Temperature (C)',font=font(18),fill='#8a987e')
im.save(OUT/'cooling-curve.png')
print('Generated original tea-cup.png and cooling-curve.png')
