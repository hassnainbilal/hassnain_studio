"""Small reusable FFmpeg filter builders for automatic video enhancement."""
def enhancement_filters(brightness=0.0, contrast=1.0, saturation=1.0, sharpness=0.0, denoise=True):
    filters=[]
    if denoise: filters.append('hqdn3d=2:1.5:3:3')
    if brightness or contrast != 1 or saturation != 1:
        filters.append(f'eq=brightness={brightness}:contrast={contrast}:saturation={saturation}')
    if sharpness: filters.append(f'unsharp=5:5:{min(2.0,max(0.0,sharpness))}:5:5:0')
    return filters
