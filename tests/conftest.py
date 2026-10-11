"""Run GUI regression tests without hardware, remote imagery, or saved user state."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['WAVESENTRY_DEMO_MAP'] = 'schematic'
os.environ['D4D_NU87_DISABLED'] = '1'
