"""Author M1 study geometry in source cm, using the acquired pampas atlas.

These meshes are procedural replacements, not extracted original game meshes.
Run with Blender's bundled Python -I; output is a new directory.
"""

import argparse
import json
import math
from pathlib import Path
import random


def normalized(v):
    length = math.sqrt(sum(x*x for x in v))
    return [x / max(length, 1e-12) for x in v]


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def part(name, texture=None):
    return dict(hash=name, identifier='Procedurally authored study geometry: '+name, lod=None,
                metadata=dict(record_offset=0, textures=[dict(name=texture)] if texture else []),
                positions=[], indices=[], normals=[], uvs=[[]], colors=[[]],
                tangents=[], extra_vectors=[], unconverted_formats=[])


def vertex(mesh, p, normal, uv=(0, 0), color=(1, 1, 1, 1)):
    mesh['positions'].append([x * 100 for x in p])
    mesh['normals'].append(normalized(normal))
    mesh['uvs'][0].append(list(uv))
    mesh['colors'][0].append(list(color))


def ribbon(mesh, centers, width, angle, uv, flex, phase, plant_height):
    base = len(mesh['positions'])
    span = [math.cos(angle), math.sin(angle), 0]
    for i, p in enumerate(centers):
        t = i / (len(centers)-1)
        previous, following = centers[max(0, i-1)], centers[min(len(centers)-1, i+1)]
        tangent = [following[k]-previous[k] for k in range(3)]
        normal = normalized(cross(span, tangent))
        w = width(t)
        for side in (-1, 1):
            position = [p[k] + side * span[k] * w for k in range(3)]
            rounded = normalized([normal[k] + side*0.28*span[k] for k in range(3)])
            weight = min(1, max(0, p[2]/plant_height))
            vertex(mesh, position, rounded,
                   (uv[0] if side == -1 else uv[1], uv[3] - t*(uv[3]-uv[2])),
                   (weight, flex, phase, weight*weight))
    for i in range(len(centers)-1):
        a = base + i*2
        mesh['indices'].extend([a,a+1,a+3,a,a+3,a+2])


def stem(mesh, centers, phase, plant_height):
    base = len(mesh['positions'])
    for i, p in enumerate(centers):
        t = i/(len(centers)-1)
        radius = 0.0055*(1-t*0.55)
        weight = min(1, p[2]/plant_height)
        for j in range(4):
            a = j*math.tau/4
            vertex(mesh, (p[0]+math.cos(a)*radius,p[1]+math.sin(a)*radius,p[2]),
                   (math.cos(a),math.sin(a),0), (j/4,t), (weight,0,phase,weight*weight))
    for i in range(len(centers)-1):
        for j in range(4):
            a,b = base+i*4+j,base+i*4+(j+1)%4
            mesh['indices'].extend([a,b,b+4,a,b+4,a+4])


def pampas(index):
    rng = random.Random(2026110600 + index)
    stems, leaves, heads = part('StudyStems'), part('StudyLeaves', 'foliage_dl_pampasgrass_001.msac.d.0.sps'), part('StudyPlumes', 'foliage_dl_pampasgrass_001.msac.d.0.sps')
    fuzz=part('StudyFuzz','fxt_or_034_pampas_fluff.psd.0.sps')
    for i in range([6,7,5,8][index]):
        a = rng.uniform(0,math.tau)
        root = [math.cos(a)*rng.uniform(.05,.23),math.sin(a)*rng.uniform(.05,.23)]
        height = rng.uniform(1.05,1.42)
        lean = rng.uniform(.22,.48)
        phase = rng.random()
        centers = [[root[0]+math.sin(a)*.08*t*t,root[1]-lean*t*t,height*t]
                   for t in [j/9 for j in range(10)]]
        stem(stems,centers,phase,1.8)
        end=centers[-1]
        head_length = rng.uniform(.35,.5)
        head_lean=rng.uniform(.16,.34)
        head_centers=[[end[0]+.08*t,end[1]-head_lean*t,end[2]+head_length*.85*t-.05*t*t]
                      for t in [j/7 for j in range(8)]]
        rect = (.025,.64,.998,.776) if i%2 == 0 else (.67,.998,.998,.776)
        for angle in (0,math.pi/2):
            ribbon(heads,head_centers,lambda t: .057*(.8+.2*math.sin(math.pi*t)),
                   angle,rect,1,phase,1.8)
        axis=normalized([.08,-head_lean,head_length*.85])
        basis=normalized(cross(axis,[0,0,1]));other=cross(axis,basis)
        for level in range(5):
            t=.15+level*.16
            p=[end[0]+.08*t,end[1]-head_lean*t,end[2]+head_length*.85*t-.05*t*t]
            radius=.048*(1-t)**.55+.01
            for arm in range(4):
                angle=arm*math.pi/2+phase*2
                radial=[basis[k]*math.cos(angle)+other[k]*math.sin(angle) for k in range(3)]
                centers=[[p[k]+radial[k]*radius*u+axis[k]*.07*u for k in range(3)] for u in (0,.5,1)]
                ribbon(fuzz,centers,lambda u:.014*(.45+.55*math.sin(math.pi*u)),angle,(0,1,0,1),1,phase,1.8)
    for i in range(14):
        a = rng.uniform(0,math.tau)
        length = rng.uniform(.7,1.15)
        centers=[[math.cos(a)*(.06+.48*t),math.sin(a)*(.06+.48*t)-.10*t*t,
                  .035+length*t-.46*t*t] for t in [j/6 for j in range(7)]]
        ribbon(leaves,centers,lambda t: .065*(.22+.78*math.sin(math.pi*t)**.6),
               a+math.pi/2,(.001,.998,.02,.765),.55,rng.random(),1.8)
    return [stems,leaves,heads,fuzz]


def terrain_height(x,y):
    return (.35*math.sin(x/30)+.2*math.sin(y/16)+.45*math.sin(x/43+y/31)
            +2.0*math.exp(-((x-78)/36)**2)*(0.3+0.7/(1+math.exp(-y/20)))
            +2.5*max(0,x/180)**2)


def ground():
    mesh=part('StudyTerrain')
    xs=[-8+i*2 for i in range(119)]
    ys=[-180+i*3 for i in range(121)]
    for x in xs:
        for y in ys:
            z=terrain_height(x,y)
            dx=(terrain_height(x+.1,y)-terrain_height(x-.1,y))/.2
            dy=(terrain_height(x,y+.1)-terrain_height(x,y-.1))/.2
            vertex(mesh,(x,y,z),(-dx,-dy,1),(x/24,y/24))
    for i in range(len(xs)-1):
        for j in range(len(ys)-1):
            a=i*len(ys)+j;b=a+len(ys)
            mesh['indices'].extend([a,b,b+1,a,b+1,a+1])
    return [mesh]


def ridge(index):
    mesh=part('StudyRidge')
    n=101
    for row in range(5):
        x=(row-2)*22
        for i in range(n):
            y=-900+i*18
            profile=(18+9*math.sin(y/94+index)+4*math.sin(y/36+index*.7)
                     +11*math.exp(-((y+200-index*210)/120)**2))*(1+index*.23)
            z=profile*(.7+.3*math.cos(x/70)) if abs(row-2)<2 else -12
            vertex(mesh,(x,y,z),(0,0,1),(row/4,i/(n-1)))
    for row in range(4):
        for i in range(n-1):
            a=row*n+i;b=a+n
            mesh['indices'].extend([a,b,b+1,a,b+1,a+1])
    return [mesh]


def rock():
    mesh=part('StudyRock')
    phi=(1+math.sqrt(5))/2
    points=[(-1,phi,0),(1,phi,0),(-1,-phi,0),(1,-phi,0),(0,-1,phi),(0,1,phi),(0,-1,-phi),(0,1,-phi),(phi,0,-1),(phi,0,1),(-phi,0,-1),(-phi,0,1)]
    points=[normalized(p) for p in points]
    faces=[(0,11,5),(0,5,1),(0,1,7),(0,7,10),(0,10,11),(1,5,9),(5,11,4),(11,10,2),(10,7,6),(7,1,8),(3,9,4),(3,4,2),(3,2,6),(3,6,8),(3,8,9),(4,9,5),(2,4,11),(6,2,10),(8,6,7),(9,8,1)]
    for _ in range(2):
        cache={};new_faces=[]
        def midpoint(a,b):
            key=tuple(sorted((a,b)))
            if key not in cache:
                cache[key]=len(points);points.append(normalized([(points[a][k]+points[b][k])/2 for k in range(3)]))
            return cache[key]
        for a,b,c in faces:
            ab,bc,ca=midpoint(a,b),midpoint(b,c),midpoint(c,a)
            new_faces.extend([(a,ab,ca),(b,bc,ab),(c,ca,bc),(ab,bc,ca)])
        faces=new_faces
    for i,p in enumerate(points):
        f=1+.1*math.sin(i*12.7)+.08*math.cos(p[0]*7+p[1]*5)
        vertex(mesh,(p[0]*f,p[1]*f*.82,p[2]*f*.66),p,(p[0],p[1]))
    mesh['indices']=[i for face in faces for i in face]
    return [mesh]


def bird():
    mesh=part('StudyKiteSilhouette')
    outlines=[[(0,.03,0),(.24,.17,.03),(.63,.10,-.045),(.55,-.05,-.02),(.19,-.07,0)],
              [(0,-.03,0),(-.24,.17,.03),(-.63,.10,-.045),(-.55,-.05,-.02),(-.19,-.07,0)],
              [(-.045,-.05,0),(0,.24,.025),(.045,-.05,0),(.11,-.27,-.01),(0,-.19,-.015),(-.11,-.27,-.01)]]
    for outline in outlines:
        base=len(mesh['positions'])
        for p in outline:vertex(mesh,p,(0,0,1),(p[0],p[1]))
        for i in range(1,len(outline)-1):mesh['indices'].extend([base,base+i,base+i+1])
    return [mesh]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    parser.add_argument('--pampas-only',action='store_true')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    objects={f'SM_Pampas_Study_{chr(65+i)}':pampas(i) for i in range(4)}
    if not args.pampas_only:
        objects.update(SM_Terrain_Study=ground(),SM_Rock_Study=rock(),SM_Kite_Study=bird())
        objects.update({f'SM_Ridge_Study_{chr(65+i)}':ridge(i) for i in range(3)})
    manifest=[]
    for name,parts in objects.items():
        for p in parts:
            assert len(p['positions'])==len(p['uvs'][0])==len(p['normals'])==len(p['colors'][0])
            assert max(p['indices'])<len(p['positions']) and len(p['indices'])%3==0
            assert all(math.isfinite(v) for row in p['positions'] for v in row)
            p['bounds']=[[min(v[k] for v in p['positions']),max(v[k] for v in p['positions'])] for k in range(3)]
        data=dict(build='Authored study replacement',source_mesh='Procedural geometry',uv_origin='top-left',
                  coordinates='Authored Z-up centimetres',parts=parts,
                  wind_color_contract='R=normalized height; G=flex class; B=phase seed; A=height squared. Not original game semantics.')
        path=args.output/(name+'.json');path.write_text(json.dumps(data,separators=(',',':')),'utf-8')
        manifest.append(dict(name=name,json=str(path.resolve()),vertices=sum(len(p['positions']) for p in parts),
                             triangles=sum(len(p['indices'])//3 for p in parts),sections=len(parts)))
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2),'utf-8')
    print('Authored and checked',len(manifest),'study meshes')


if __name__=='__main__':main()
