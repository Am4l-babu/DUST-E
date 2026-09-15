"""
binbrain.vision - camera, detector, appearance, tracker, geometry.

Importing this package does not import OpenCV. camera.py and the detector
backends import it lazily, so the tracker, the geometry and every test run on a
machine with nothing but numpy installed.
"""
