"""生成 sample/ 示例图片（纯色块等几何图形，Pillow 现造，无网络）。"""

import os
from PIL import Image, ImageDraw

os.makedirs(os.path.dirname(os.path.abspath(__file__)), exist_ok=True)
HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 640, 480


def save(img, name):
    img.save(os.path.join(HERE, name), "JPEG", quality=88)
    print("saved", name)


# 1) 深蓝夜空 + 橙色尖塔（模拟"东京塔"）
im = Image.new("RGB", (W, H), (12, 18, 55))
d = ImageDraw.Draw(im)
d.rectangle([250, 200, 390, 470], fill=(190, 90, 40))
d.polygon([(250, 200), (320, 90), (390, 200)], fill=(215, 120, 55))
d.rectangle([260, 300, 380, 330], fill=(255, 190, 90))
for x in range(0, W, 40):
    d.line([(x, 470), (x + 20, 300)], fill=(255, 220, 120), width=2)
save(im, "IMG_20230101_103055.jpg")

# 2) 暖黄背景 + 圆形"餐盘"（模拟美食）
im = Image.new("RGB", (W, H), (255, 236, 200))
d = ImageDraw.Draw(im)
d.ellipse([140, 110, 500, 400], fill=(235, 235, 235), outline=(180, 160, 120), width=8)
d.ellipse([180, 150, 460, 360], fill=(230, 150, 60))
d.ellipse([240, 200, 400, 320], fill=(250, 210, 120))
for i in range(6):
    d.ellipse([250 + i * 22, 220, 270 + i * 22, 240], fill=(90, 140, 60))
save(im, "IMG_20230615_140020.jpg")

# 3) 绿色草地 + 白色小狗轮廓（模拟宠物）
im = Image.new("RGB", (W, H), (140, 200, 120))
d = ImageDraw.Draw(im)
d.rectangle([0, 340, W, H], fill=(90, 150, 70))
d.ellipse([260, 260, 380, 370], fill=(245, 235, 210))
d.ellipse([330, 210, 390, 290], fill=(245, 235, 210))
d.ellipse([300, 230, 345, 275], fill=(200, 160, 90))
d.ellipse([332, 228, 342, 238], fill=(30, 30, 30))
d.ellipse([352, 245, 366, 259], fill=(30, 30, 30))
d.ellipse([230, 320, 280, 380], fill=(245, 235, 210))
d.ellipse([380, 320, 430, 380], fill=(245, 235, 210))
save(im, "photo_20240801.jpg")

print("done: 3 sample images in", HERE)
