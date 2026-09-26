"""Pure crop/rotation geometry used by the visual correction editor."""
from dataclasses import dataclass

@dataclass
class CropModel:
    width: float; height: float; left: float; top: float; right: float; bottom: float; angle: float=0.0
    def clamp(self):
        self.left=max(0,min(self.left,self.width-2));self.right=max(self.left+2,min(self.right,self.width));self.top=max(0,min(self.top,self.height-2));self.bottom=max(self.top+2,min(self.bottom,self.height));return self
    def move(self,dx,dy):self.left+=dx;self.right+=dx;self.top+=dy;self.bottom+=dy;return self.clamp()
    def set_edge(self,edge,x,y):
        if "l" in edge:self.left=x
        if "r" in edge:self.right=x
        if "t" in edge:self.top=y
        if "b" in edge:self.bottom=y
        return self.clamp()
    @property
    def center(self):return ((self.left+self.right)/2,(self.top+self.bottom)/2)
