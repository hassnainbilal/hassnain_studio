"""Deterministic image diagnostics and conservative per-image enhancement."""
from PIL import Image, ImageStat, ImageFilter, ImageEnhance, ImageOps
import numpy as np
import cv2

def analyze_image(image):
    rgb = np.asarray(ImageOps.exif_transpose(image).convert('RGB'))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    brightness = float(gray.mean() / 255)
    contrast = float(gray.std() / 128)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    blur_score = float(1 / (1 + sharpness / 100))
    noise = float(np.mean(np.abs(gray.astype(float)-cv2.medianBlur(gray, 3).astype(float))))
    means = rgb.reshape(-1,3).mean(axis=0)
    return {'width': int(rgb.shape[1]), 'height': int(rgb.shape[0]), 'resolution': f'{rgb.shape[1]}x{rgb.shape[0]}',
      'brightness': round(brightness,4), 'exposure': 'underexposed' if brightness < .30 else 'overexposed' if brightness > .78 else 'balanced',
      'contrast': round(contrast,4), 'sharpness': round(sharpness,2), 'blur_score': round(blur_score,4),
      'blur': 'likely' if sharpness < 45 else 'low', 'noise': round(noise,2),
      'saturation': round(float(hsv[:,:,1].mean()/255),4), 'color_rgb_mean': [round(float(x),1) for x in means],
      'white_balance': 'warm' if means[0] > means[2]*1.12 else 'cool' if means[2] > means[0]*1.12 else 'neutral'}

def auto_enhance(image):
    report = analyze_image(image)
    im = ImageOps.exif_transpose(image).convert('RGB')
    b = report['brightness']; c = report['contrast']
    if b < .38: im = ImageEnhance.Brightness(im).enhance(min(1.35, .38/max(b,.08)))
    elif b > .72: im = ImageEnhance.Brightness(im).enhance(max(.82, .72/b))
    if c < .75: im = ImageEnhance.Contrast(im).enhance(1.12)
    if report['noise'] > 5:
        arr = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)
        im = Image.fromarray(cv2.cvtColor(cv2.fastNlMeansDenoisingColored(arr,None,5,5,7,21),cv2.COLOR_BGR2RGB))
    if report['sharpness'] < 180: im = ImageEnhance.Sharpness(im).enhance(1.25)
    return im, report
