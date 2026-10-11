"""Native cartography and continuous track rendering for the fictional demo."""
from math import atan2, cos, sin, pi, hypot
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget, QSizePolicy
from .demo_model import SCENES, SPOT_DURATION, degree, course_text


BG = '#10191f'


def ink(value, alpha=1):
    color = QColor(value)
    color.setAlphaF(alpha)
    return color


class DemoMap(QWidget):
    selected = Signal(str)

    def __init__(self, model):
        super().__init__()
        self.model = model
        self.track_id = 'H-01'
        self.trails = True
        self.uncertainty = True
        self.all_labels = False
        self.hit_boxes = []
        self.label_boxes = []
        self.cache_key = None
        self.label_anchors = {}
        self.spot_halo = QPixmap(512,512)
        self.spot_halo.fill(Qt.transparent)
        halo=QPainter(self.spot_halo)
        gradient=QRadialGradient(256,256,256)
        for at,alpha in [(0,0),(.81,0),(.85,.18),(.87,.58),(.91,.22),(1,0)]:
            gradient.setColorAt(at,ink('#ff4557',alpha))
        halo.fillRect(self.spot_halo.rect(),gradient);halo.end()
        self.setMinimumSize(400, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName('상황지도 · 관측 기록에서도 기체를 선택할 수 있습니다')

    def coordinates(self):
        w, h = self.width(), self.height()
        return w * .51, h * .53, min(w * .445, (h - 76) * .49)

    def point(self, x, y):
        return QPointF(self.cx + x * self.scale, self.cy - y * self.scale)

    @staticmethod
    def line(p, a, b, color, width=1, dash=False):
        pen = QPen(QColor(color) if isinstance(color, str) else color, width)
        if dash:
            pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.drawLine(a, b)

    @staticmethod
    def text(p, x, y, text, color='#99acb5', size=10, bold=False):
        font = QFont('Consolas')
        font.setPixelSize(size)
        font.setBold(bold)
        p.setFont(font)
        p.setPen(QColor(color) if isinstance(color, str) else color)
        p.drawText(QPointF(x, y), text)

    def basemap(self, p):
        S = self.S
        def point(x, y):
            return QPointF(self.cx + x * S, self.cy - y * S)
        def path(pts, color='#34454e', width=.8, fill=None, dash=False):
            poly = QPolygonF([point(x, y) for x, y in pts])
            pen = QPen(QColor(color), width) if color else QPen(Qt.NoPen)
            if dash:
                pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.setBrush(QColor(fill) if fill else Qt.NoBrush)
            p.drawPolygon(poly) if fill else p.drawPolyline(poly)
        def box(x, y, w, h, fill='#1e2e37', stroke='#3b4f59'):
            path([(x,y),(x+w,y),(x+w,y+h),(x,y+h)], stroke, .7, fill)
        def road(pts, major=False):
            path(pts, BG, 6 if major else 3)
            path(pts, '#53636b' if major else '#384b55', 2.3 if major else 1)
            if major:
                path(pts, BG, .8)
        def field(pts):
            path(pts, '#21352f', .7, '#152822')
        def blocks(x,y,cols,rows,dx,dy):
            for j in range(rows):
                for i in range(cols):
                    box(x+i*dx+.025,y+j*dy+.023,dx*(.48+(i+j)%3*.08),dy*(.43+(i*2+j)%3*.09))
        self.place_labels = []
        def label(text,x,y):
            pt = point(x,y)
            rect = QRectF(pt.x()-len(text)*2.8,pt.y()-10,len(text)*5.6,15)
            if QRectF(8,55,self.width()-16,self.height()-103).contains(rect):
                self.place_labels.append((text,rect))
        p.fillRect(self.rect(), QColor(BG))
        field([(-2,-1.2),(-1.4,-.9),(-1.15,-.45),(-1.45,.1),(-2,.22)])
        field([(.73,.66),(1.1,.55),(1.5,.82),(2.2,.62),(2.2,1.5),(.9,1.5)])
        for k in range(6):
            path([(.73+j*.075,.71+k*.11+sin(j*.34+k*.4)*.075) for j in range(22)], '#263b33', .65)
        for k in range(5):
            path([(-2,-.95+k*.19),(-1.72,-.81+k*.17),(-1.39,-.85+k*.2),(-1.19,-.71+k*.15)], '#263b33', .65)
        if self.model.site == 'airbase':
            bank=[(-2,-.82),(-1.55,-.68),(-1.07,-.65),(-.67,-.77),(-.22,-.88),(.22,-.82),(.72,-.7),(1.21,-.79),(1.72,-.92),(2.1,-.81)]
            other=[(x,y-.1-.025*sin(i)) for i,(x,y) in enumerate(bank)]
            path(bank+other[::-1], '#304b58', .7, '#16323f')
            path([(x,y-.2) for x,y in bank])
            road([(-2,.6),(-1.4,.52),(-.91,.43),(-.44,.54),(.06,.75),(.65,.77),(1.21,.65),(2.1,.7)],True)
            road([(-1.43,-1.4),(-1.19,-.51),(-1.15,.05),(-.91,.43),(-.8,1.4)],True)
            road([(.52,-1.4),(.4,-.62),(.53,-.2),(.93,.22),(1.19,.64),(1.23,1.4)])
            road([(-1.14,.03),(-.64,.04),(-.09,.08),(.43,.2),(.94,.22)])
            path([(-1.04,-.4),(-.75,.09),(.17,.37),(.45,.17),(.42,-.36),(-.35,-.67),(-1.04,-.4)],dash=True)
            p.save()
            p.translate(point(-.27,-.21))
            p.rotate(-18.33)
            p.setPen(QPen(QColor('#53666e'),.8))
            p.setBrush(QColor('#26343c'))
            p.drawRect(QRectF(-S*.65,-S*.041,S*1.3,S*.082))
            self.line(p,QPointF(-S*.6,0),QPointF(S*.6,0),'#8a9ca1',.9,True)
            for end in [-1,1]:
                for j in range(-2,3):
                    self.line(p,QPointF(end*S*.595,j*2.2),QPointF(end*S*.553,j*2.2),'#94a7ab',.8)
            self.line(p,QPointF(-S*.56,S*.13),QPointF(S*.54,S*.13),'#455862')
            for j in [-1,0,1]:
                self.line(p,QPointF(j*S*.3,S*.041),QPointF(j*S*.3,S*.13),'#455862')
            self.text(p,-S*.53,3,'09',size=9)
            self.text(p,S*.48,3,'27',size=9)
            p.restore()
            box(-.72,-.56,.65,.16)
            blocks(-.7,-.56,5,1,.125,.14)
            road([(-.77,-.55),(-.88,-.36),(-.83,-.1),(-.63,.04)])
            blocks(-1.91,.70,6,3,.14,.12)
            blocks(1.27,-.43,4,4,.17,.13)
            for j in range(4):
                road([(-1.95,.67+j*.15),(-1.04,.67+j*.15)])
            road([(1.21,-.52),(2.1,-.52)])
            road([(1.2,-.07),(2.1,-.07)])
            label('SERVICE ROAD',-.5,.65)
            label('HANGAR APRON',-.42,-.66)
            label('EAST ACCESS',1.1,.15)
        elif self.model.site == 'facility':
            river=[(-2,-.93),(-1.31,-.77),(-.72,-.89),(-.12,-1.04),(.5,-1),(1.1,-.88),(2,-1.03)]
            path(river+[(x,y-.11) for x,y in river[::-1]],'#304b58',.7,'#16323f')
            for j in range(-3,4):
                road([(-2.1,j*.3-.02),(2.1,j*.3+.04)],abs(j)==2)
            for i in range(-5,6):
                road([(i*.36-.06,-1.5),(i*.36+.06,1.5)],abs(i)==3)
            for j in range(-3,4):
                for i in range(-5,5):
                    if -1<=i<=1 and -1<=j<=1:
                        continue
                    blocks(i*.36+.03,j*.3+.03,2,2,.14,.12)
            path([(-.49,-.39),(-.49,.48),(.48,.48),(.57,.07),(.45,-.43),(-.49,-.39)],'#4c6363',1,'#152323')
            road([(-.47,-.22),(.48,-.22),(.42,.38),(-.34,.38),(-.34,-.22)])
            box(-.23,-.1,.28,.2,'#293b42','#68818a')
            box(.11,-.06,.19,.27)
            box(-.26,.22,.26,.1)
            box(.1,.28,.24,.1)
            for j in range(5):
                path([(-.42,-.31+j*.04),(-.29,-.31+j*.04)])
            label('RESEARCH CAMPUS',-.05,.53)
            label('SOUTH AVENUE',.64,-.56)
            label('SERVICE YARD',.76,.4)
        else:
            road([(-2,-.72),(-1.04,-.65),(-.4,-.73),(.19,-.65),(.69,-.65),(1.38,-.43),(2,-.49)],True)
            road([(-.93,-1.5),(-.85,-.65),(-.9,-.12),(-.7,.56),(-.77,1.5)],True)
            road([(1.06,-1.4),(.8,-.64),(.72,-.06),(.94,.73),(1.27,1.5)])
            field([(-.64,-.54),(-.59,.65),(.56,.75),(.64,-.48)])
            path([(-.64,-.54),(-.64,.67),(.51,.76),(.67,.18),(.63,-.54),(-.64,-.54)],dash=True)
            box(-.2,-.23,.4,.13,'#2b3e43','#687f85')
            box(-.32,.02,.63,.1)
            box(-.26,-.6,.5,.3,'#1a2e30')
            for i in range(8):
                path([(-.25,-.57+i*.034),(.23,-.57+i*.034)])
            road([(-.61,-.45),(-.35,-.42),(-.35,.4),(.43,.42),(.47,-.49),(.61,-.49)])
            for i in range(4):
                box(-.56,-.33+i*.17,.13,.1)
                box(.43,-.31+i*.17,.12,.1)
            blocks(-1.77,-.43,4,6,.19,.2)
            blocks(1.11,-.3,4,5,.21,.18)
            for j in range(3):
                road([(1.03,-.35+j*.4),(2.1,-.35+j*.4)])
            for j in range(10):
                path([(.09+j*.047,-.96),(.09+j*.047,-.82)])
            label('STAGE',0,-.19)
            label('AUDIENCE',-.01,-.69)
            label('BACKSTAGE',-.01,.2)
            label('PARKING',.38,-1.08)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor('#28383f'),.8))
        for f in [.5,1]:
            p.drawEllipse(QPointF(self.cx,self.cy),S*f,S*f)
        for a in range(0,360,15):
            t = a*pi/180
            inner = S-(7 if a%90==0 else 3)
            self.line(p,QPointF(self.cx+cos(t)*inner,self.cy+sin(t)*inner),QPointF(self.cx+cos(t)*S,self.cy+sin(t)*S),'#34424a',.7)
        zone = SCENES[self.model.site].zone*self.scale
        p.setPen(QPen(ink('#d5c287',.45),1,Qt.DashLine))
        p.drawEllipse(QPointF(self.cx,self.cy),zone,zone)

    def paintEvent(self, event):
        self.cx,self.cy,self.S = self.coordinates()
        scene = SCENES[self.model.site]
        self.scale = self.S/scene.radius
        key=(self.size(),self.devicePixelRatioF(),self.model.site)
        if self.cache_key != key:
            self.cache_key=key
            self.label_anchors.clear()
            self.base=QPixmap(self.size()*self.devicePixelRatioF())
            self.base.setDevicePixelRatio(self.devicePixelRatioF())
            b=QPainter(self.base)
            b.setRenderHint(QPainter.Antialiasing)
            self.basemap(b)
            b.end()
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.drawPixmap(0,0,self.base)
        for pulse in self.model.spot_pulses():
            progress=pulse['age']/SPOT_DURATION
            alpha=sin(pi*progress)**.85
            radius=self.S*1.2*(1+.035*progress)
            p.save();p.setOpacity(alpha*.85)
            p.drawPixmap(QRectF(self.cx-radius,self.cy-radius,2*radius,2*radius),self.spot_halo,QRectF(self.spot_halo.rect()))
            p.restore()
            angle=pulse['bearing']*pi/180
            arc=QPolygonF([QPointF(self.cx+sin(angle-.24+i*.02)*self.S*1.05,
                                  self.cy-cos(angle-.24+i*.02)*self.S*1.05) for i in range(25)])
            p.setBrush(Qt.NoBrush);p.setPen(QPen(ink('#ff6472',alpha*.8),1.6));p.drawPolyline(arc)
        tracks=self.model.tracks()
        marker_boxes=[]
        for d in tracks:
            if not self.model.bearing_only(d):
                pos=self.point(d['x'],d['y'])
                marker_boxes.append(QRectF(pos.x()-15,pos.y()-15,30,30))
        fixed=[QRectF(0,0,230,59),QRectF(self.width()-75,0,75,70),
               QRectF(0,self.height()-46,115,46),QRectF(self.width()-220,self.height()-33,220,33),
               QRectF(self.cx-35,self.cy-14,70,46),QRectF(self.cx-26,self.cy-scene.zone*self.scale-26,52,20)]
        occupied=fixed+marker_boxes
        self.hit_boxes=[]
        self.label_boxes=[]
        for d in sorted(tracks,key=lambda d:d['id']!=self.track_id):
            history=self.model.trail(d['id']) if self.trails else []
            selected=d['id']==self.track_id
            bearing=self.model.bearing_only(d)
            color='#91a0a8' if self.model.stale else d['color']
            pos=self.point(d['x'],d['y'])
            direction=atan2(-d['vy'],d['vx'])
            if bearing:
                a=atan2(-d['y'],d['x'])
                pos=QPointF(self.cx+cos(a)*self.S*.8,self.cy+sin(a)*self.S*.8)
                poly=QPolygonF([QPointF(self.cx,self.cy)]+[QPointF(self.cx+cos(a-.12+j*.012)*self.S,self.cy+sin(a-.12+j*.012)*self.S) for j in range(21)])
                p.setPen(QPen(ink(color,.4),.8))
                p.setBrush(ink(color,.07))
                p.drawPolygon(poly)
                self.line(p,QPointF(self.cx,self.cy),QPointF(self.cx+cos(a)*self.S,self.cy+sin(a)*self.S),ink(color,.7),1,True)
            else:
                for i in range(1,len(history)):
                    a,b=history[i-1],history[i]
                    self.line(p,self.point(a['x'],a['y']),self.point(b['x'],b['y']),ink(color,.12+i/len(history)*.6),1.5 if selected else 1,self.model.stale)
                    if i%5==0:
                        p.setBrush(ink(color,.8)); p.setPen(Qt.NoPen)
                        p.drawEllipse(self.point(b['x'],b['y']),1.6,1.6)
                if selected:
                    self.line(p,QPointF(self.cx,self.cy),pos,ink(color,.25),.8,True)
                    if self.uncertainty and not self.model.stale:
                        p.setBrush(ink(color,.1));p.setPen(QPen(ink(color,.5),.8))
                        p.drawEllipse(pos,scene.error*self.scale,scene.error*self.scale)
                    for sx in [-1,1]:
                        for sy in [-1,1]:
                            a=pos+QPointF(sx*9,sy*14);b=pos+QPointF(sx*14,sy*14);c=pos+QPointF(sx*14,sy*9)
                            self.line(p,a,b,color);self.line(p,b,c,color)
                if not self.model.stale:
                    end=self.point(d['x']+d['vx']*20,d['y']+d['vy']*20)
                    self.line(p,pos,end,ink(color,.65),1)
                    for offset in [-.45,.45]:
                        self.line(p,end,end-QPointF(cos(direction+offset)*6,sin(direction+offset)*6),color,1)
                p.save();p.translate(pos)
                p.setPen(QPen(QColor(color),1.6));p.setBrush(QColor(BG))
                if d['affiliation']=='아군':
                    p.rotate(direction*180/pi+90)
                    p.drawPolygon(QPolygonF([QPointF(0,-7),QPointF(5.5,5),QPointF(0,2),QPointF(-5.5,5)]))
                elif d['affiliation']=='적군':
                    p.drawPolygon(QPolygonF([QPointF(0,-6),QPointF(6,0),QPointF(0,6),QPointF(-6,0)]))
                else:
                    p.drawEllipse(QPointF(0,0),5,5)
                p.restore()
                self.hit_boxes.append((d['id'],QRectF(pos.x()-12,pos.y()-12,24,24)))
            lines=[f"{d['id']}   {d['affiliation']}"]
            if self.model.stale:
                lines.append(f'LAST {self.model.age:.0f}s · — m/s · —°')
            elif bearing:
                lines.append('BRG '+degree(d['bearing'])+' · 거리 미확정')
            else:
                lines.append(f"{d['speed']:.1f} m/s   {course_text(d['course'])}")
            if (selected or self.all_labels) and not bearing:
                lines.append(f"R {d['distance']:.0f}m  BRG {degree(d['bearing'])}")
            font=QFont('Consolas');font.setPixelSize(11);p.setFont(font)
            bw=max(158,max(p.fontMetrics().horizontalAdvance(s) for s in lines)+16)
            bh=len(lines)*17+10
            px,py=pos.x(),pos.y()
            candidates=[(px+24,py-bh-14),(px+24,py+16),(px-bw-24,py-bh-14),(px-bw-24,py+16),
                        (px-bw/2,py-bh-32),(px-bw/2,py+32),(px+42,py-bh/2),(px-bw-42,py-bh/2)]
            # Reuse a valid relative anchor, just like the satellite overlay.
            anchor=self.label_anchors.get(d['id'])
            held=None
            if anchor and anchor[2:]==(bw,bh):
                rect=QRectF(px+anchor[0],py+anchor[1],bw,bh)
                padded=rect.adjusted(-4,-4,4,4)
                if (rect.left()>=8 and rect.right()<=self.width()-8 and rect.top()>=60
                        and rect.bottom()<=self.height()-40
                        and not any(padded.intersects(a) for a in occupied)):
                    held=(rect.x(),rect.y())
            if held:
                candidates=[held]
            else:
                candidates += [(x,y) for x in range(9,max(10,int(self.width()-bw)),40)
                               for y in range(61,max(62,int(self.height()-bh-40)),30)]
            best=None
            for x,y in candidates:
                rect=QRectF(max(8,min(x,self.width()-bw-8)),max(60,min(y,self.height()-bh-40)),bw,bh)
                padding=rect.adjusted(-4,-4,4,4)
                score=sum((lambda r:r.width()*r.height())(padding.intersected(a)) for a in occupied)*40
                score+=hypot(rect.center().x()-px,rect.center().y()-py)
                if best is None or score<best[0]:
                    best=(score,rect)
            rect=best[1]
            self.label_anchors[d['id']]=(rect.x()-px,rect.y()-py,bw,bh)
            occupied.append(rect)
            self.label_boxes.append((d['id'],rect))
            self.hit_boxes.append((d['id'],rect))
            nearest=QPointF(max(rect.left(),min(px,rect.right())),max(rect.top(),min(py,rect.bottom())))
            self.line(p,pos,nearest,ink(color,.6),.8)
            p.setPen(Qt.NoPen);p.setBrush(ink('#17252d',.96) if selected else ink(BG,.92));p.drawRect(rect)
            if selected:
                self.line(p,rect.topLeft(),rect.topRight(),ink(color,.85),1)
            for i,text in enumerate(lines):
                self.text(p,rect.x()+8,rect.y()+15+i*17,text,color if i==0 else '#d2dddf' if i==1 else '#8fa3ad',11,i==1)
        for text,rect in self.place_labels:
            if not any(rect.intersects(a) for a in occupied):
                self.text(p,rect.x(),rect.y()+10,text,'#6e858d',10)
        p.setPen(QPen(QColor('#c1d5d3'),1));p.setBrush(QColor('#21363c'))
        p.drawRect(QRectF(self.cx-6,self.cy-6,12,12))
        for dx in [-2,2]:
            for dy in [-2,2]:
                p.fillRect(QRectF(self.cx+dx-1,self.cy+dy-1,2,2),QColor('#a4dcc8'))
        self.text(p,self.cx-14,self.cy+24,scene.array,'#c6d5d8',11)
        self.text(p,self.cx-24,self.cy-scene.zone*self.scale-12,'보호구역','#b7aa88',10)
        p.fillRect(QRectF(0,0,self.width(),29),ink(BG,.94))
        self.text(p,12,19,scene.name,'#b7c9d0',11)
        self.text(p,self.width()-135,19,f'반경 {scene.radius:g} m','#8398a3',10)
        self.text(p,12,48,'LAST · 갱신 중단' if self.model.stale else 'LIVE / 연속 추적','#c2cecc',10)
        self.text(p,self.width()-29,47,'N','#bbccd1',11)
        self.line(p,QPointF(self.width()-26,66),QPointF(self.width()-26,52),'#96afb9')
        self.line(p,QPointF(self.width()-26,52),QPointF(self.width()-30,58),'#96afb9')
        self.line(p,QPointF(self.width()-26,52),QPointF(self.width()-22,58),'#96afb9')
        dist=500 if self.model.site=='airbase' else 200 if self.model.site=='facility' else 50
        x,y,bar=16,self.height()-20,dist*self.scale
        p.fillRect(QRectF(8,y-25,100,38),ink(BG,.9))
        self.line(p,QPointF(x,y),QPointF(x+bar,y),'#96afb9')
        for xx in [x,x+bar]:
            self.line(p,QPointF(xx,y-3),QPointF(xx,y+3),'#96afb9')
        self.text(p,x,y-8,f'{dist} m','#b5c8cc',10)
        self.text(p,self.width()-202,self.height()-15,'△ 아군   ◇ 적군   ○ 미식별','#b5c8cc',11)
        p.end()

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:
            for ident,rect in reversed(self.hit_boxes):
                if rect.contains(event.position()):
                    self.selected.emit(ident)
                    break
        super().mousePressEvent(event)
