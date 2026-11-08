"""Turntable animation: the camera circles once around the scene, saved as an animated GIF."""

import numpy as np
from PIL import Image


def frames(scene, count=72, width=720, progress=None):
    """Images of one full circle around the focal point (the camera is put back afterwards)."""
    plotter = scene.plotter
    camera = plotter.camera
    before = scene.current_view()
    scene.flight.stop()
    images = []
    try:
        for index in range(count):
            plotter.ren_win.Render()  # the plotter's own render() is deferred to the event loop
            pixels = plotter.screenshot(return_img=True)[:, :, :3]
            image = Image.fromarray(np.ascontiguousarray(pixels))
            if image.width > width:
                image = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
            images.append(image)
            camera.Azimuth(360.0 / count)
            plotter.renderer.ResetCameraClippingRange()
            if progress is not None and progress(index + 1, count) is False:
                return None  # cancelled
    finally:
        scene.go_to_view(before, animate=False)
    return images


def save_gif(path, images, seconds=6.0):
    """One loop of the animation takes `seconds`."""
    duration = max(20, round(seconds * 1000 / len(images)))
    first, *rest = [image.convert("P", palette=Image.ADAPTIVE, colors=255) for image in images]
    first.save(str(path), save_all=True, append_images=rest, duration=duration, loop=0, optimize=False)
