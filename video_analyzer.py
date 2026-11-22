"""Video metadata and sampled-frame quality/content analysis using FFmpeg/OpenCV."""
import cv2, subprocess, json
from fractions import Fraction

def analyze_video(path):
    p = subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,text=True,check=True)
    data=json.loads(p.stdout); v=next((s for s in data.get('streams',[]) if s.get('codec_type')=='video'),{})
    duration=float(data.get('format',{}).get('duration') or 0); fps=float(Fraction(v.get('avg_frame_rate','0/1'))) if v.get('avg_frame_rate') else 0.0
    cap=cv2.VideoCapture(str(path)); samples=[]; scenes=[]; prev=None; count=max(1,min(12,int(duration/3)+1))
    for i in range(count):
        cap.set(cv2.CAP_PROP_POS_MSEC, (duration*(i+.5)/count)*1000); ok,frame=cap.read()
        if not ok: continue
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY); samples.append((float(gray.mean()/255),float(gray.std()/128),float(cv2.Laplacian(gray,cv2.CV_64F).var())))
        if prev is not None and cv2.mean(cv2.absdiff(gray,prev))[0] > 25: scenes.append(round(duration*(i+.5)/count,2))
        prev=gray
    cap.release(); avg=[sum(x[k] for x in samples)/len(samples) for k in range(3)] if samples else [0,0,0]
    aspect=round((v.get('width') or 1)/(v.get('height') or 1),3)
    return {'duration':round(duration,2),'width':v.get('width'),'height':v.get('height'),'fps':round(fps,3),'has_audio':any(s.get('codec_type')=='audio' for s in data.get('streams',[])),
      'aspect_ratio':aspect,'aspect_label':'vertical' if aspect<.85 else 'square' if .85<=aspect<=1.15 else 'landscape',
      'brightness':round(avg[0],3),'contrast':round(avg[1],3),'sharpness':round(avg[2],2),'blur':'likely' if avg[2]<45 else 'low','scene_changes':scenes,
      'recommended_template':'Reels and Instagram Stories' if aspect<.85 else 'Cinematic' if duration>90 else 'Dynamic Montage'}
