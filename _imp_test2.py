import sys
sys.path.insert(0, '.')
import ui.timeline_canvas as t
print('OK load:', hasattr(t, 'TimelineCanvas'))
from ui.timeline_canvas import TimelineCanvas
print('Instantiating...')
obj = TimelineCanvas()
print('Has pdf btn:', hasattr(obj, '_pdf_btn'))
