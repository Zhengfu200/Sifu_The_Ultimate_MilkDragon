"""Fit source geometry to the unmodified game reference skeleton, in centimetres.

The source mesh has no rig. Limb regions are identified by surface distance in
build_model; the mapping here uses distance along each limb, never world height.
"""
from mathutils import Vector


def smooth(a, b, value):
    t = max(0.0, min(1.0, (value - a) / (b - a)))
    return t * t * (3 - 2 * t)


class Limb:
    def __init__(self, source, target, names, radius_scale=1.0):
        self.source = source
        self.target = target
        self.names = names
        self.radius_scale = radius_scale
        self.lengths = [(b - a).length for a, b in zip(source, source[1:])]
        self.starts = [0.0]
        for length in self.lengths:
            self.starts.append(self.starts[-1] + length)
        self.rotations = [(b - a).rotation_difference(d - c) for a, b, c, d in
                          zip(source, source[1:], target, target[1:])]

    def fit(self, point):
        candidates = []
        for i, (a, b) in enumerate(zip(self.source, self.source[1:])):
            direction = b - a
            raw = (point - a).dot(direction) / direction.length_squared
            t = min(1.0, max(0.0, raw))
            candidates.append(((point - a.lerp(b, t)).length_squared, i, raw))
        _, segment, t = min(candidates)
        # Allow the end caps to extend beyond the first and last landmarks.
        t = max(0.0, t) if segment else t
        t = min(1.0, t) if segment < len(self.lengths) - 1 else t
        source_center = self.source[segment].lerp(self.source[segment + 1], t)
        target_center = self.target[segment].lerp(self.target[segment + 1], t)
        distance = self.starts[segment] + t * self.lengths[segment]
        rotation = self.rotations[segment]
        # Smooth the cross-section frame across joints without moving joint centres.
        for joint in range(1, len(self.lengths)):
            width = min(self.lengths[joint - 1], self.lengths[joint]) * .22
            if abs(distance - self.starts[joint]) < width:
                blend = smooth(self.starts[joint] - width, self.starts[joint] + width, distance)
                rotation = self.rotations[joint - 1].slerp(self.rotations[joint], blend)
        fitted = target_center + rotation @ ((point - source_center) * self.radius_scale)

        weights = {self.names[min(segment, len(self.names) - 1)]: 1.0}
        for joint in range(1, len(self.names)):
            width = min(self.lengths[joint - 1], self.lengths[min(joint, len(self.lengths) - 1)]) * .24
            if abs(distance - self.starts[joint]) < width:
                blend = smooth(self.starts[joint] - width, self.starts[joint] + width, distance)
                weights = {self.names[joint - 1]: 1 - blend, self.names[joint]: blend}
        if self.names[0].startswith("upperarm_"):
            side = self.names[0][-1]
            # Original twist bones are siblings of each segment, not successive
            # joints. Interpolate their influences along that segment's axis.
            nodes = [(0.0, "upperarm"), (.25, "upperarm_twist_01"),
                     (.50, "upperarm_twist_02"), (.72, "upperarm_twist_03"),
                     (.88, "upperarm_twist_04"), (1.08, "lowerarm"),
                     (1.30, "lowerarm_twist_01"), (1.50, "lowerarm_twist_02"),
                     (1.70, "lowerarm_twist_03"), (1.85, "lowerarm_twist_04"),
                     (2.12, "hand")]
            coordinate = segment + t
            weights = {f"hand_{side}": 1.0}
            for (lo, a), (hi, b) in zip(nodes, nodes[1:]):
                if coordinate <= hi:
                    blend = smooth(lo, hi, coordinate)
                    weights = {f"{a}_{side}": 1 - blend, f"{b}_{side}": blend}
                    break
        return fitted, weights


class ReferenceFit:
    def __init__(self, world, transform, arm, leg, torso):
        self.world = world
        self.transform = transform
        self.torso = torso
        self.offsets = {name: world[name].translation - transform(Vector((0, -.035 if z < .45 else -.045, z)))
                        for z, name in torso}
        self.limbs = {}
        for side, sign in (("l", -1), ("r", 1)):
            source = [transform(Vector((sign * x, y, z))) for x, y, z in arm]
            # A palm-length extension lets the wrist and palm have separate frames.
            source.append(source[-1] + (source[-1] - source[-2]).normalized() * 11)
            names = [f"{name}_{side}" for name in ("upperarm", "lowerarm", "hand")]
            target = [world[name].translation.copy() for name in names]
            finger = next((f"{stem}_01_{side}" for stem in ("middle", "index") if f"{stem}_01_{side}" in world), None)
            direction = (world[finger].translation - target[-1]) if finger else target[-1] - target[-2]
            target.append(target[-1] + direction.normalized() * 10)
            self.limbs["arm", side] = Limb(source, target, names, .90)
            source = [transform(Vector((sign * x, y, z))) for x, y, z in leg]
            names = [f"{name}_{side}" for name in ("thigh", "calf", "foot", "ball")]
            target = [world[name].translation.copy() for name in names]
            source.append(source[-1] + (source[-1] - source[-2]).normalized() * 6)
            target.append(target[-1] + (target[-1] - target[-2]).normalized() * 6)
            self.limbs["leg", side] = Limb(source, target, names, .94)

    def body(self, source):
        z = source.z
        for (lo, a), (hi, b) in zip(self.torso, self.torso[1:]):
            if z <= hi:
                t = smooth(lo, hi, z)
                weights = {a: 1 - t, b: t}
                linear = max(0.0, min(1.0, (z - lo) / (hi - lo)))
                offsets = {a: 1 - linear, b: linear}
                break
        else:
            weights = {self.torso[-1][1]: 1.0}
            offsets = weights
        point = self.transform(source)
        # Keep the head broad; narrow the shoulder/belly slightly for arm clearance.
        width = .88 + .12 * smooth(.45, .68, z)
        point.x *= width
        point.y *= .87 + .13 * smooth(.35, .65, z)
        for name, weight in offsets.items():
            point += self.offsets[name] * weight
        return point, weights

    def vertex(self, source, arm_mask):
        body, weights = self.body(source)
        side = "l" if source.x <= 0 else "r"
        if source.z < -.28:
            amount = smooth(.045, .15, abs(source.x)) * (1 - smooth(-.51, -.28, source.z))
            kind = "leg"
        else:
            amount = arm_mask
            kind = "arm"
        if amount <= 0:
            return body, weights
        limb, limb_weights = self.limbs[kind, side].fit(self.transform(source))
        result = {name: w * (1 - amount) for name, w in weights.items()}
        for name, w in limb_weights.items():
            result[name] = result.get(name, 0) + w * amount
        return body.lerp(limb, amount), result
