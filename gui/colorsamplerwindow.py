import gtk
gdk = gtk.gdk
from math import pi, sin, cos, sqrt, atan2
import struct
import cairo
import windowing
from lib.helpers import rgb_to_hsv, hsv_to_rgb, clamp
import colorhistory as ch
from gettext import gettext as _

CSTEP=0.007
PADDING=4

class GColorSelector(gtk.DrawingArea):
    def __init__(self, init_dnd=True):
        gtk.DrawingArea.__init__(self)
        self.color = (1,0,0)
        self.hsv = (0,1,1)
        self.connect('expose-event', self.draw)
        self.set_events(gdk.BUTTON_PRESS_MASK |
                        gdk.BUTTON_RELEASE_MASK |
                        gdk.POINTER_MOTION_MASK |
                        gdk.ENTER_NOTIFY |
                        gdk.LEAVE_NOTIFY |
                        gdk.DROP_FINISHED |
                        gdk.DROP_START |
                        gdk.DRAG_STATUS)
        self.connect('button-press-event', self.on_button_press)
        self.connect('button-release-event', self.on_button_release)
        self.connect('configure-event', self.on_configure)
        self.connect('motion-notify-event', self.motion)
        if init_dnd:
            self.connect('drag_data_get', self.drag_get)
        self.button_pressed = False
        self.do_select = True
        self.grabbed = False
        self.dnd_enabled = init_dnd
        self.set_size_request(80, 80)

    def test_drag(self,x,y,d):
        return d>20

    def move(self,x,y):
        pass

    def redraw_on_select(self):
        self.queue_draw()

    def motion(self,w, event):
        if not self.button_pressed:
            return
        d = sqrt((event.x-self.press_x)**2 + (event.y-self.press_y)**2)
        if self.dnd_enabled and self.test_drag(event.x,event.y, d):
            self.do_select = False
            self.drag_begin([("application/x-color",0,80)], gdk.ACTION_COPY, 1, event)
        else:
            if not self.grabbed:
                self.grabbed = True
                self.grab_add()
            self.move(event.x,event.y)

    def drag_get(self, widget, context, selection, targetType, eventTime):
        try:
            color, is_hsv = self.get_color_at(self.press_x, self.press_y)
        except TypeError:
            return
        if is_hsv:
            r,g,b = hsv_to_rgb(*color)
        else:
            r,g,b = color
        r = min(int(r*65536), 65535)
        g = min(int(g*65536), 65535)
        b = min(int(b*65536), 65535)
        clrs = struct.pack('HHHH',r,g,b,0)
        selection.set(selection.target, 8, clrs)

    def on_configure(self,w, size):
        self.x_rel = size.x
        self.y_rel = size.y
        self.w = size.width
        self.h = size.height
        self.configure_calc()

    def configure_calc(self):
        pass

    def on_select(self,color):
        pass

    def record_button_press(self, x,y):
        pass

    def get_color_at(self, x,y):
        return self.color, False

    def select_color_at(self, x,y):
        try:
            color, is_hsv = self.get_color_at(x,y)
        except TypeError:
            return
        if is_hsv:
            self.hsv = color
            self.color = hsv_to_rgb(*color)
        else:
            self.color = color
            self.hsv = rgb_to_hsv(*color)
        self.redraw_on_select()
        self.on_select(self.color)

    def set_color(self, color):
        self.color = color
        self.hsv = rgb_to_hsv(*color)
        self.queue_draw()

    def get_color(self):
        return self.color

    def on_button_press(self,w, event):
        self.button_pressed = True
        self.do_select = True
        self.press_x = event.x
        self.press_y = event.y
        self.record_button_press(event.x, event.y)

    def on_button_release(self,w, event):
        if self.button_pressed and self.do_select:
            self.select_color_at(event.x,event.y)
        self.button_pressed = False
        if self.grabbed:
            self.grab_remove()
            self.grabbed = False

    def draw(self,w,event):
        if not self.window:
            return
        cr = self.window.cairo_create()
        cr.set_source_rgb(*self.color)
        cr.rectangle(PADDING,PADDING, self.w-2*PADDING, self.h-2*PADDING)
        cr.fill()

class RectSlot(GColorSelector):
    def __init__(self,color=(1.0,1.0,1.0),size=32):
        GColorSelector.__init__(self)
        self.color = color
        self.set_size_request(size,size)

class RecentColors(gtk.HBox):
    def __init__(self):
        gtk.HBox.__init__(self)
        self.set_border_width(4)
        self.N = N = ch.num_colors
        self.slots = []
        for i,color in enumerate(reversed(ch.colors)):
            slot = RectSlot(color=color)
            slot.on_select = self.slot_selected
            self.pack_start(slot, expand=True)
            self.slots.append(slot)
        self.show_all()
        ch.on_color_pushed = self.refill_slots

    def slot_selected(self,color):
        self.on_select(color)

    def on_select(self,color):
        pass

    def refill_slots(self, pushed_color):
        for color,slot in zip(ch.colors, reversed(self.slots)):
            slot.set_color(hsv_to_rgb(*color))

    def set_color(self, color):
        pass

CIRCLE_N = 12.0
SLOTS_N = 5

AREA_SQUARE = 1
AREA_SAMPLE = 2
AREA_CIRCLE = 3

sq32 = sqrt(3)/2
sq33 = sqrt(3)/3
sq36 = sq33/2
sq22 = sqrt(2)/2

def try_put(list, item):
    if not item in list:
        list.append(item)

class CircleSelector(GColorSelector):
    def __init__(self, color=(1,0,0)):
        GColorSelector.__init__(self)
        self.color = color
        self.hsv = rgb_to_hsv(*color)

        self.samples = []      # [(h,s,v)] -- list of `harmonic' colors
        self.last_line = None  # 

        # Whether to show harmonies
        self.complimentary = False
        self.triadic = False
        self.double_comp = False
        self.split_comp = False
        self.analogous = False
        self.square = False

    def get_previous_color(self):
        return self.color

    def calc_line(self, angle):
        x1 = self.x0 + self.r2*cos(-angle)
        y1 = self.y0 + self.r2*sin(-angle)
        x2 = self.x0 + self.r3*cos(-angle)
        y2 = self.y0 + self.r3*sin(-angle)
        return x1,y1,x2,y2

    def configure_calc(self):
        self.x0 = self.x_rel + self.w/2.0
        self.y0 = self.y_rel + self.h/2.0
        self.M = M = min(self.w,self.h)-2
        self.rd = 0.31*M       # gives size of square
        self.r2 = 0.42*M      # Inner radius of hue ring
        self.r3 = M/2.0
        self.m = self.rd/sqrt(2.0)
        self.circle_img = None
        self.stroke_width = 0.015*M

    def set_color(self, color, redraw=True):
        self.color = color
        h,s,v = rgb_to_hsv(*color)
        old_h,old_s,old_v = self.hsv
        self.hsv = h,s,v
        if redraw:
            self.queue_draw()

    def test_drag(self,x,y,dist):
        area = self.area_at(self.press_x,self.press_y)
        return area == AREA_SAMPLE

    def nearest_dragable(self, x,y):
        area_source = self.area_at(self.press_x, self.press_y)
        area = self.area_at(x,y)
        if area == area_source and area in [AREA_CIRCLE, AREA_SQUARE]:
            return x,y
        dx = x-self.x0
        dy = y-self.y0
        d = sqrt(dx*dx+dy*dy)
        x1 = dx/d
        y1 = dy/d
        if area_source == AREA_CIRCLE:
            rx = self.x0 + (self.r2+3.0)*x1
            ry = self.y0 + (self.r2+3.0)*y1
        else:
            tx = self.rd*x1
            ty = self.rd*y1
            m = self.m-1.0
            rx = self.x0 + clamp(tx, -m, +m)
            ry = self.y0 + clamp(ty, -m, +m)
        return rx,ry

    def move(self,x,y):
        x_,y_ = self.nearest_dragable(x,y)
        self.select_color_at(x_,y_)

    def area_at(self, x,y):
        dx = x-self.x0
        dy = y-self.y0
        d = sqrt(dx*dx+dy*dy)
        if self.r2 < d < self.r3:
            return AREA_CIRCLE
        elif self.rd < d < self.r2:
            return AREA_SAMPLE
        elif abs(dx)<self.m and abs(dy)<self.m:
            return AREA_SQUARE

    def get_color_at(self, x,y):
        area = self.area_at(x,y)
        if not area:
            return
        if area == AREA_CIRCLE:
            h,s,v = self.hsv
            h = 0.5 + 0.5*atan2(y-self.y0, self.x0-x)/pi
            return (h,s,v), True
        elif area == AREA_SAMPLE:
            a = pi+atan2(y-self.y0, self.x0-x)
            for i,a1 in enumerate(self.angles):
                if a1-2*pi/CIRCLE_N < a < a1:
                    clr = self.simple_colors[i]
                    return clr, False
        elif area == AREA_SQUARE:
            h,s,v = self.hsv
            s = (x-self.x0+self.m)/(2*self.m)
            v = (y-self.y0+self.m)/(2*self.m)
            return (h,s,1-v), True

    def draw_square(self,width,height,radius):
        img = cairo.ImageSurface(cairo.FORMAT_ARGB32, width,height)
        cr = cairo.Context(img)
        h,s,v = self.hsv
        m = radius/sqrt(2.0)
        ds = 2*m*CSTEP
        v = 0.0
        x1 = self.x0-m
        x2 = self.x0+m
        y = self.y0-m
        while v < 1.0:
            y += ds
            g = cairo.LinearGradient(x1,y,x2,y)
            g.add_color_stop_rgb(0.0, *hsv_to_rgb(h,0.0,1.0-v))
            g.add_color_stop_rgb(1.0, *hsv_to_rgb(h,1.0,1.0-v))
            cr.set_source(g)
            cr.rectangle(x1,y, 2*m, ds)
            cr.fill_preserve()
            cr.stroke()
            v += CSTEP
        h,s,v = self.hsv
        x = self.x0-m + s*2*m
        y = self.y0-m + (1-v)*2*m
        cr.set_source_rgb(*hsv_to_rgb(1-h,1-s,1-v))
        cr.arc(x,y, 3.0, 0.0, 2*pi)
        cr.stroke()
        return img

    def small_circle(self, cr, size, color, angle, rad):
        x0 = self.x0 + rad*cos(angle)
        y0 = self.y0 + rad*sin(angle)
        cr.set_source_rgb(*color)
        cr.arc(x0,y0,size/2., 0, 2*pi)
        cr.fill()

    def small_triangle(self, cr, size, color, angle, rad):
        x0 = self.x0 + rad*cos(angle)
        y0 = self.y0 + rad*sin(angle)
        x1,y1 = x0, y0 - size*sq32
        x2,y2 = x0 + 0.5*size, y0 + size*sq36
        x3,y3 = x0 - 0.5*size, y0 + size*sq36
        cr.set_source_rgb(*color)
        cr.move_to(x1,y1)
        cr.line_to(x2,y2)
        cr.line_to(x3,y3)
        cr.line_to(x1,y1)
        cr.fill()

    def small_triangle_down(self, cr, size, color, angle, rad):
        x0 = self.x0 + rad*cos(angle)
        y0 = self.y0 + rad*sin(angle)
        x1,y1 = x0, y0 + size*sq32
        x2,y2 = x0 + 0.5*size, y0 - size*sq36
        x3,y3 = x0 - 0.5*size, y0 - size*sq36
        cr.set_source_rgb(*color)
        cr.move_to(x1,y1)
        cr.line_to(x2,y2)
        cr.line_to(x3,y3)
        cr.line_to(x1,y1)
        cr.fill()

    def small_square(self, cr, size, color, angle, rad):
        x0 = self.x0 + rad*cos(angle)
        y0 = self.y0 + rad*sin(angle)
        x1,y1 = x0+size*sq22, y0+size*sq22
        x2,y2 = x0+size*sq22, y0-size*sq22
        x3,y3 = x0-size*sq22, y0-size*sq22
        x4,y4 = x0-size*sq22, y0+size*sq22
        cr.set_source_rgb(*color)
        cr.move_to(x1,y1)
        cr.line_to(x2,y2)
        cr.line_to(x3,y3)
        cr.line_to(x4,y4)
        cr.fill()

    def small_rect(self, cr, size, color, angle, rad):
        x0 = self.x0 + rad*cos(angle)
        y0 = self.y0 + rad*sin(angle)
        x1,y1 = x0+size*sq22, y0+size*0.3
        x2,y2 = x0+size*sq22, y0-size*0.3
        x3,y3 = x0-size*sq22, y0-size*0.3
        x4,y4 = x0-size*sq22, y0+size*0.3
        cr.set_source_rgb(*color)
        cr.move_to(x1,y1)
        cr.line_to(x2,y2)
        cr.line_to(x3,y3)
        cr.line_to(x4,y4)
        cr.fill()

    def small_rect_vert(self, cr, size, color, angle, rad):
        x0 = self.x0 + rad*cos(angle)
        y0 = self.y0 + rad*sin(angle)
        x1,y1 = x0+size*0.3, y0+size*sq22
        x2,y2 = x0+size*0.3, y0-size*sq22
        x3,y3 = x0-size*0.3, y0-size*sq22
        x4,y4 = x0-size*0.3, y0+size*sq22
        cr.set_source_rgb(*color)
        cr.move_to(x1,y1)
        cr.line_to(x2,y2)
        cr.line_to(x3,y3)
        cr.line_to(x4,y4)
        cr.fill()

    def inv(self, rgb):
        r,g,b = rgb
        return 1-r,1-g,1-b

    def draw_inside_circle(self,width,height):
        if not self.window:
            return
        points_size = min(width,height)/27.
        img = cairo.ImageSurface(cairo.FORMAT_ARGB32, width,height)
        cr = cairo.Context(img)
        h,s,v = self.hsv
        a = h*2*pi
        self.angles = []
        self.simple_colors = []
        cr.set_line_width(self.stroke_width)
        self.samples = [self.hsv]
        for i in range(int(CIRCLE_N)):
            c1 = c = h + i/CIRCLE_N
            if c1 > 1:
                c1 -= 1
            clr = hsv_to_rgb(c1,s,v)
            hsv = c1,s,v
            self.simple_colors.append(clr)
            delta = c1 - h
            an = -c1*2*pi
            self.angles.append(-an+pi/CIRCLE_N)
            a1 = an-pi/CIRCLE_N
            a2 = an+pi/CIRCLE_N
            cr.new_path()
            cr.set_source_rgb(*clr)
            cr.move_to(self.x0,self.y0)
            cr.arc(self.x0, self.y0, self.r2, a1, a2)
            cr.line_to(self.x0,self.y0)
            cr.fill_preserve()
            cr.set_source_rgb(0.5,0.5,0.5)
            cr.stroke()
            # Indicate harmonic colors
            if self.triadic and i%(CIRCLE_N/3)==0:
                self.small_triangle(cr, points_size, self.inv(clr), an, (self.r2+self.rd)/2)
                try_put(self.samples, hsv)
            if self.complimentary and i%(CIRCLE_N/2)==0:
                self.small_circle(cr, points_size, self.inv(clr), an, (self.r2+self.rd)/2)
                try_put(self.samples, hsv)
            if self.square and i%(CIRCLE_N/4)==0:
                self.small_square(cr, points_size, self.inv(clr), an, (self.r2+self.rd)/2)
                try_put(self.samples, hsv)
# FIXME: should this harmonies be expressed in terms of CIRCLE_N?
            if self.double_comp and i in [0,2,6,8]:
                self.small_rect_vert(cr, points_size, self.inv(clr), an, (self.r2+self.rd)/2)
                try_put(self.samples, hsv)
            if self.split_comp and i in [0,5,7]:
                self.small_triangle_down(cr, points_size, self.inv(clr), an, (self.r2+self.rd)/2)
                try_put(self.samples, hsv)
            if self.analogous and i in [0,1,CIRCLE_N-1]:
                self.small_rect(cr, points_size, self.inv(clr), an, (self.r2+self.rd)/2)
                try_put(self.samples, hsv)
        x1 = self.x0 + self.r2*cos(-a)
        y1 = self.y0 + self.r2*sin(-a)
        x2 = self.x0 + self.r3*cos(-a)
        y2 = self.y0 + self.r3*sin(-a)
        self.last_line = x1,y1, x2,y2, h
        cr.set_line_width(0.8*self.stroke_width)
        cr.set_source_rgb(0,0,0)
        cr.move_to(x1,y1)
        cr.line_to(x2,y2)
        cr.stroke()
        cr.set_source_rgb(0.5,0.5,0.5)
        cr.arc(self.x0, self.y0, self.rd, 0, 2*pi)
        cr.fill()
        return img

    def draw_circles(self, cr):
        cr.set_line_width(self.stroke_width)
        cr.set_source_rgb(0.5,0.5,0.5)
        cr.arc(self.x0,self.y0, self.r2, 0, 2*pi)
        cr.stroke()
        cr.arc(self.x0,self.y0, self.r3, 0, 2*pi)
        cr.stroke()
        
    def draw_circle(self, w, h):
        if self.circle_img:
            return self.circle_img
        img = cairo.ImageSurface(cairo.FORMAT_ARGB32, w,h)
        cr = cairo.Context(img)
        cr.set_line_width(0.8*self.stroke_width)
        a1 = 0.0
        while a1 < 2*pi:
            clr = hsv_to_rgb(a1/(2*pi), 1.0, 1.0)
            x1,y1,x2,y2 = self.calc_line(a1)
            a1 += CSTEP
            cr.set_source_rgb(*clr)
            cr.move_to(x1,y1)
            cr.line_to(x2,y2)
            cr.stroke()
        self.circle_img = img
        return img

    def draw(self,w,event):
        if not self.window:
            return
        cr = self.window.cairo_create()
        cr.set_source_surface(self.draw_circle(self.w,self.h))
        cr.paint()
        cr.set_source_surface(self.draw_inside_circle(self.w,self.h))
        cr.paint()
        self.draw_circles(cr)
        cr.set_source_surface(self.draw_square(self.w,self.h, self.rd*0.92))
        cr.paint()
        sq2 = sqrt(2.0)
        M = self.M/2.0
        r = (sq2-1)*M/(2*sq2)
        x0 = self.x0+M-r
        y0 = self.y0+M-r
        cr.set_source_rgb(*self.color)
        cr.arc(x0, y0, 0.9*r, -pi/2, pi/2)
        cr.fill()
        cr.set_source_rgb(*self.get_previous_color())
        cr.arc(x0, y0, 0.9*r, pi/2, 3*pi/2)
        cr.fill()
        cr.arc(x0, y0, 0.9*r, 0, 2*pi)
        cr.set_source_rgb(0.5,0.5,0.5)
        cr.set_line_width(0.8*self.stroke_width)
        cr.stroke()

class VSelector(GColorSelector):
    def __init__(self, color=(1,0,0), height=16):
        GColorSelector.__init__(self, init_dnd=False)
        self.color = color
        self.hsv = rgb_to_hsv(*color)
        self.set_size_request(height*2,height)

    def get_color_at(self, x,y):
        h,s,v = self.hsv
        v = x/self.w
        return (h,s,v), True

    def move(self, x,y):
        self.select_color_at(x,y)

    def draw_gradient(self,cr, start,end, hsv=True):
        if hsv:
            clr1 = hsv_to_rgb(*start)
            clr2 = hsv_to_rgb(*end)
        else:
            clr1 = start
            clr2 = end
        g = cairo.LinearGradient(0,0,self.w,self.h)
        g.add_color_stop_rgb(0.0, *clr1)
        g.add_color_stop_rgb(1.0, *clr2)
        cr.set_source(g)
        cr.rectangle(0,0,self.w,self.h)
        cr.fill()

    def draw_line_at(self, cr, x):
        cr.set_source_rgb(0,0,0)
        cr.move_to(x,0)
        cr.line_to(x, self.h)
        cr.stroke()

    def draw(self,w, event):
        if not self.window:
            return
        cr = self.window.cairo_create()
        h,s,v = self.hsv
        self.draw_gradient(cr, (h,s,0.), (h,s,1.))

        x1 = v*self.w
        self.draw_line_at(cr, x1)

class HSelector(VSelector):
    def get_color_at(self,x,y):
        h,s,v = self.hsv
        h = x/self.w
        return (h,s,v), True
    
    def draw(self,w, event):
        if not self.window:
            return
        cr = self.window.cairo_create()
        h,s,v = self.hsv
        dx = self.w*CSTEP
        x = 0
        h1 = 0.
        while h1 < 1:
            cr.set_source_rgb(*hsv_to_rgb(h1,s,v))
            cr.rectangle(x,0,dx,self.h)
            cr.fill_preserve()
            cr.stroke()
            h1 += CSTEP
            x += dx
        x1 = h*self.w
        self.draw_line_at(cr, x1)

class SSelector(VSelector):
    def get_color_at(self, x,y):
        h,s,v = self.hsv
        s = x/self.w
        return (h,s,v), True

    def draw(self,w, event):
        if not self.window:
            return
        cr = self.window.cairo_create()
        h,s,v = self.hsv
        self.draw_gradient(cr, (h,0.,v), (h,1.,v))

        x1 = s*self.w
        self.draw_line_at(cr, x1)

class RSelector(VSelector):
    def get_color_at(self,x,y):
        r,g,b = self.color
        r = x/self.w
        return (r,g,b), False
    
    def draw(self,w, event):
        if not self.window:
            return
        cr = self.window.cairo_create()
        r,g,b = self.color
        self.draw_gradient(cr, (0.,g,b),(1.,g,b), hsv=False)
        x1 = r*self.w
        self.draw_line_at(cr,x1)

class GSelector(VSelector):
    def get_color_at(self,x,y):
        r,g,b = self.color
        g = x/self.w
        return (r,g,b), False
    
    def draw(self,w, event):
        if not self.window:
            return
        cr = self.window.cairo_create()
        r,g,b = self.color
        self.draw_gradient(cr, (r,0.,b),(r,1.,b), hsv=False)
        x1 = g*self.w
        self.draw_line_at(cr,x1)

class BSelector(VSelector):
    def get_color_at(self,x,y):
        r,g,b = self.color
        b = x/self.w
        return (r,g,b), False
    
    def draw(self,w, event):
        if not self.window:
            return
        cr = self.window.cairo_create()
        r,g,b = self.color
        self.draw_gradient(cr, (r,g,0.),(r,g,1.), hsv=False)
        x1 = b*self.w
        self.draw_line_at(cr,x1)

def make_spin(min,max, changed_cb):
    adj = gtk.Adjustment(0,min,max, 1,10)
    btn = gtk.SpinButton(adj)
    btn.connect('value-changed', changed_cb)
    btn.set_sensitive(False)
    return btn

class HSVSelector(gtk.VBox):
    def __init__(self, color=(1.,0.,0)):
        gtk.VBox.__init__(self)
        self.color = color
        self.hsv = rgb_to_hsv(*color)
        self.atomic = False

        hbox = gtk.HBox()
        self.hsel = hsel = HSelector(color)
        hsel.on_select = self.user_selected_color
        self.hspin = hspin = make_spin(0,359, self.hue_change)
        hbox.pack_start(hsel, expand=True)
        hbox.pack_start(hspin, expand=False)

        sbox = gtk.HBox()
        self.ssel = ssel = SSelector(color)
        ssel.on_select = self.user_selected_color
        self.sspin = sspin = make_spin(0,100, self.sat_change)
        sbox.pack_start(ssel, expand=True)
        sbox.pack_start(sspin, expand=False)

        vbox = gtk.HBox()
        self.vsel = vsel = VSelector(color)
        vsel.on_select = self.user_selected_color
        self.vspin = vspin = make_spin(0,100, self.val_change)
        vbox.pack_start(vsel, expand=True)
        vbox.pack_start(vspin, expand=False)
        
        self.pack_start(hbox, expand=False)
        self.pack_start(sbox, expand=False)
        self.pack_start(vbox, expand=False)

    def user_selected_color(self, color):
        self.set_color(color)
        self.on_select(color)

    def set_color(self, color):
        self.atomic = True
        h,s,v = rgb_to_hsv(*color)
        self.hspin.set_value(h*359)
        self.sspin.set_value(s*100)
        self.vspin.set_value(v*100)
        self.hsel.set_color(color)
        self.ssel.set_color(color)
        self.vsel.set_color(color)
        self.atomic = False
        self.color = color
        self.hsv = rgb_to_hsv(*color)

    def on_select(self, color):
        pass

    def hue_change(self, spin):
        if self.atomic:
            return
        h,s,v = self.hsv
        self.set_color(hsv_to_rgb(spin.get_value()/359., s,v))

    def sat_change(self, spin):
        if self.atomic:
            return
        h,s,v = self.hsv
        self.set_color(hsv_to_rgb(h, spin.get_value()/100., v))

    def val_change(self, spin):
        if self.atomic:
            return
        h,s,v = self.hsv
        self.set_color(hsv_to_rgb(h,s, spin.get_value()/100.))

class RGBSelector(gtk.VBox):
    def __init__(self, color=(1.,0.,0)):
        gtk.VBox.__init__(self)
        self.color = color
        self.hsv = rgb_to_hsv(*color)
        self.atomic = False

        rbox = gtk.HBox()
        self.rsel = rsel = RSelector(color)
        rsel.on_select = self.user_selected_color
        self.rspin = rspin = make_spin(0,255, self.r_change)
        rbox.pack_start(rsel, expand=True)
        rbox.pack_start(rspin, expand=False)

        gbox = gtk.HBox()
        self.gsel = gsel = GSelector(color)
        gsel.on_select = self.user_selected_color
        self.gspin = gspin = make_spin(0,255, self.g_change)
        gbox.pack_start(gsel, expand=True)
        gbox.pack_start(gspin, expand=False)

        bbox = gtk.HBox()
        self.bsel = bsel = BSelector(color)
        bsel.on_select = self.user_selected_color
        self.bspin = bspin = make_spin(0,255, self.b_change)
        bbox.pack_start(bsel, expand=True)
        bbox.pack_start(bspin, expand=False)
        
        self.pack_start(rbox, expand=False)
        self.pack_start(gbox, expand=False)
        self.pack_start(bbox, expand=False)

    def user_selected_color(self, color):
        self.set_color(color)
        self.on_select(color)

    def set_color(self, color):
        self.atomic = True
        r,g,b = color
        self.rspin.set_value(r*255)
        self.gspin.set_value(g*255)
        self.bspin.set_value(b*255)
        self.rsel.set_color(color)
        self.gsel.set_color(color)
        self.bsel.set_color(color)
        self.atomic = False
        self.color = color
        self.hsv = rgb_to_hsv(*color)

    def on_select(self, color):
        pass

    def r_change(self, spin):
        if self.atomic:
            return
        r,g,b = self.color
        self.set_color((spin.get_value()/255., g,b))

    def g_change(self, spin):
        if self.atomic:
            return
        r,g,b = self.color
        self.set_color((r, spin.get_value()/255., b))

    def b_change(self, spin):
        if self.atomic:
            return
        r,g,b = self.color
        self.set_color((r,g, spin.get_value()/255.))

class Selector(gtk.VBox):
    def __init__(self,app):
        gtk.VBox.__init__(self)
        self.app = app
        hbox = gtk.HBox()
        self.pack_start(hbox, expand=True)
        vbox = gtk.VBox()
        hbox.pack_start(vbox,expand=True)
        self.recent = RecentColors()
        self.circle = CircleSelector()
        vbox.pack_start(self.circle, expand=True)

        self.rgb_selector = RGBSelector()
        self.hsv_selector = HSVSelector()
        self.rgb_selector.on_select = self.rgb_selected
        self.hsv_selector.on_select = self.hsv_selected
        nb = gtk.Notebook()
        nb.append_page(self.rgb_selector, gtk.Label(_('RGB')))
        nb.append_page(self.hsv_selector, gtk.Label(_('HSV')))

        self.exp_history = expander = gtk.Expander(_('Colors history'))
        expander.set_spacing(6)
        expander.add(self.recent)
        self.pack_start(expander, expand=False)
        self.exp_details = expander = gtk.Expander(_('Details'))
        expander.set_spacing(6)
        expander.add(nb)
        self.pack_start(expander, expand=False)

        def harmony_checkbox(attr, label):
            cb = gtk.CheckButton(label)
            cb.connect('toggled', self.harmony_toggled, attr)
            vbox2.pack_start(cb, expand=False)

        self.exp_config = expander = gtk.Expander(_('Harmonies'))
        vbox2 = gtk.VBox()
        harmony_checkbox('analogous', _('Analogous'))
        harmony_checkbox('complimentary', _('Complimentary color'))
        harmony_checkbox('split_comp', _('Split complimentary'))
        harmony_checkbox('double_comp', _('Double complimentary'))
        harmony_checkbox('square', _('Square'))
        harmony_checkbox('triadic', _('Triadic'))

        frame1 = gtk.Frame(_('Select harmonies'))
        frame1.add(vbox2)
        vbox3 = gtk.VBox()
        cb_sv = gtk.CheckButton(_('Change value/saturation'))
        cb_sv.set_active(True)
        cb_sv.connect('toggled', self.toggle_blend, 'value')
        cb_opposite = gtk.CheckButton(_('Blend each color to opposite'))
        cb_opposite.connect('toggled', self.toggle_blend, 'opposite')
        cb_neg = gtk.CheckButton(_('Blend each color to negative'))
        cb_neg.connect('toggled', self.toggle_blend, 'negative')
        vbox3.pack_start(cb_sv, expand=False)
        vbox3.pack_start(cb_opposite, expand=False)
        vbox3.pack_start(cb_neg, expand=False)
        vbox_exp = gtk.VBox()
        vbox_exp.pack_start(frame1)
        expander.add(vbox_exp)
        self.pack_start(expander, expand=False)
        self.circle.on_select = self.hue_selected
        self.circle.get_previous_color = self.previous_color
        self.recent.on_select = self.recent_selected
        self.widgets = [self.circle, self.rgb_selector, self.hsv_selector, self.recent]

        self.value_blends = True
        self.opposite_blends = False
        self.negative_blends = False

        self.connect('drag_data_received',self.drag_data)
        self.drag_dest_set(gtk.DEST_DEFAULT_MOTION | gtk.DEST_DEFAULT_HIGHLIGHT | gtk.DEST_DEFAULT_DROP,
                 [("application/x-color",0,80)],
                 gtk.gdk.ACTION_COPY)

    def toggle_blend(self, checkbox, name):
        attr = name+'_blends'
        setattr(self, attr, not getattr(self, attr))

    def harmony_toggled(self, checkbox, attr):
        setattr(self.circle, attr, not getattr(self.circle, attr))
        self.queue_draw()

    def previous_color(self):
        return ch.last_color

    def set_color(self,color,exclude=None):
        for w in self.widgets:
            if w is not exclude:
                w.set_color(color)
        self.color = color
        self.on_select(color)

    def drag_data(self, widget, context, x,y, selection, targetType, time):
        r,g,b,a = struct.unpack('HHHH', selection.data)
        clr = (r/65536.0, g/65536.0, b/65536.0)
        self.set_color(clr)

    def rgb_selected(self, color):
        self.set_color(color, exclude=self.rgb_selector)

    def hsv_selected(self, color):
        self.set_color(color, exclude=self.hsv_selector)

    def hue_selected(self, color):
        self.set_color(color, exclude=self.circle)

    def recent_selected(self, color):
        self.set_color(color, exclude=self.recent)

    def on_select(self,color):
        pass

class Window(windowing.SubWindow):
    def __init__(self,app):
        windowing.SubWindow.__init__(self, app)
        self.set_title(_('MyPaint color selector'))
        self.set_role('Color selector')
        self.set_default_size(270,300)
        self.connect('delete-event', self.app.hide_window_cb)
        self.selector = Selector(app)
        self.selector.on_select = self.on_select
        self.exp_history = self.selector.exp_history
        self.exp_details = self.selector.exp_details
        self.exp_config = self.selector.exp_config
        # TODO: persistency
        #self.exp_history.set_expanded(str_to_bool( app.get_config('State', 'color_history_expanded') ))
        #self.exp_details.set_expanded(str_to_bool( app.get_config('State', 'color_details_expanded') ))
        #self.exp_config.set_expanded(str_to_bool( app.get_config('State', 'color_configure_expanded') ))
        self.add(self.selector)
        self.app.brush.settings_observers.append(self.brush_modified_cb)
        self.stop_callback = False

    def brush_modified_cb(self):
        self.stop_callback = True
        self.selector.set_color(self.app.brush.get_color_rgb())
        self.stop_callback = False

    def on_select(self, color):
        if self.stop_callback:
            return
        self.app.colorSelectionWindow.set_color_rgb(color)
        self.app.brush.set_color_rgb(color)

