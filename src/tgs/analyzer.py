"""تحلیل ساختار TGS و پیدا کردن گروه‌هایی که «متنِ Outline شده» هستند.

نوشته‌های تبدیل‌شده به Outline در Lottie معمولاً یک گروه شکل (gr) هستند که چند مسیر بسته (sh)
— یکی برای هر کانتور حروف — به‌علاوه‌ی fill/stroke و transform دارد. گاهی هر حرف گروه جداگانه دارد.
این ماژول همه‌ی چنین گروه‌ها و خوشه‌های هم‌ردیف را به‌صورت «کاندید» برمی‌گرداند.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .geometry import flatten_path, path_bbox, union_bbox
from .props import (IDENTITY, Mat, is_animated, mat_apply, mat_mul, shape_value, shape_value_at,
                    transform_matrix)

LAYER_TYPES = {0: "precomp", 1: "solid", 2: "image", 3: "null", 4: "shape", 5: "text"}


@dataclass
class Candidate:
    id: str
    kind: str                       # 'group' | 'cluster'
    comp: str                       # 'root' یا شناسه‌ی asset (precomp)
    layer_pos: int                  # اندیس لایه در لیست لایه‌های comp
    layer_name: str
    container: list[int]            # مسیر گروه والد داخل shapes (خالی = مستقیماً داخل لایه)
    members: list[int]              # اندیس گروه(ها) داخل container
    n_paths: int = 0
    n_vertices: int = 0
    local_bbox: tuple[float, float, float, float] | None = None   # فضای container
    world_bbox: tuple[float, float, float, float] | None = None   # فضای بوم (فریم مرجع)
    fill: str | None = None
    stroke: str | None = None
    path_animated: bool = False
    group_tr_animated: bool = False
    layer_tr_animated: bool = False
    notes: list[str] = field(default_factory=list)

    def label(self) -> str:
        kind = "خوشه" if self.kind == "cluster" else "گروه"
        return f"[{self.comp}] لایه {self.layer_pos}: «{self.layer_name}» · {kind} {self.members} · {self.n_paths} مسیر"


def hex_color(c) -> str | None:
    try:
        r, g, b = (max(0, min(255, round(float(x) * 255))) for x in c[:3])
        return f"#{r:02X}{g:02X}{b:02X}"
    except Exception:  # noqa: BLE001
        return None


def get_comps(doc: dict) -> dict[str, list[dict]]:
    comps = {"root": doc.get("layers", [])}
    for a in doc.get("assets", []) or []:
        if "layers" in a:
            comps[str(a.get("id"))] = a["layers"]
    return comps


def container_items(layer: dict, container: list[int]) -> list[dict]:
    items = layer.get("shapes", [])
    for idx in container:
        items = items[idx]["it"]
    return items


def is_text_group(item: dict) -> bool:
    if item.get("ty") != "gr":
        return False
    its = item.get("it", [])
    shs = [i for i in its if i.get("ty") == "sh"]
    if not shs:
        return False
    has_style = any(i.get("ty") in ("fl", "st", "gf", "gs") for i in its)
    return has_style


def group_transform(group: dict) -> dict | None:
    for it in group.get("it", []):
        if it.get("ty") == "tr":
            return it
    return None


def group_matrix(group: dict, frame: float) -> Mat:
    tr = group_transform(group)
    return transform_matrix(tr, frame) if tr else IDENTITY


def layer_matrix(layers: list[dict], layer: dict, frame: float) -> Mat:
    """ماتریس لایه با زنجیره‌ی parent."""
    by_ind = {l.get("ind"): l for l in layers if "ind" in l}
    m = IDENTITY
    cur, guard = layer, 0
    while cur is not None and guard < 64:
        m = mat_mul(transform_matrix(cur.get("ks", {}), frame), m)
        pid = cur.get("parent")
        cur = by_ind.get(pid) if pid is not None else None
        guard += 1
    return m


def group_paths(group: dict, frame: float, matrix: Mat | None = None) -> list[dict]:
    out = []
    for it in group.get("it", []):
        if it.get("ty") == "sh":
            val = shape_value_at(it.get("ks", {}), frame)
            if val and val.get("v"):
                out.append(val)
    return out


def group_style(group: dict) -> tuple[str | None, str | None]:
    fill = stroke = None
    for it in group.get("it", []):
        if it.get("ty") == "fl" and not is_animated(it.get("c")):
            fill = hex_color(it.get("c", {}).get("k", []))
        elif it.get("ty") == "st" and not is_animated(it.get("c")):
            stroke = hex_color(it.get("c", {}).get("k", []))
    return fill, stroke


def candidate_paths(doc_layers: list[dict], layer: dict, cand: Candidate, frame: float) -> list[list[tuple[float, float]]]:
    """چندضلعی‌های کاندید در فضای container (برای خوشه: با اعمال transform اعضا)."""
    items = container_items(layer, cand.container)
    polys = []
    for gi in cand.members:
        g = items[gi]
        m = group_matrix(g, frame) if cand.kind == "cluster" else IDENTITY
        for p in group_paths(g, frame):
            polys.append(flatten_path(p, 8, m))
    return polys


def analyze(doc: dict, ref_frame: float | None = None) -> list[Candidate]:
    ip, op = doc.get("ip", 0), doc.get("op", 60)
    frame = (ip + op) / 2.0 if ref_frame is None else ref_frame
    comps = get_comps(doc)
    out: list[Candidate] = []
    for comp_id, layers in comps.items():
        for lp, layer in enumerate(layers):
            if layer.get("ty") != 4:
                continue
            lname = layer.get("nm", f"Layer {lp}")
            lm = layer_matrix(layers, layer, frame)
            l_anim = any(is_animated(layer.get("ks", {}).get(k)) for k in ("a", "p", "s", "r"))
            _walk(layer.get("shapes", []), [], comp_id, lp, lname, lm, l_anim, frame, out)
    return out


def _walk(items: list[dict], container: list[int], comp: str, lp: int, lname: str, parent_m: Mat,
          l_anim: bool, frame: float, out: list[Candidate]):
    text_idx = [i for i, it in enumerate(items) if is_text_group(it)]
    for i in text_idx:
        out.append(_make_candidate(items, container, [i], "group", comp, lp, lname, parent_m, l_anim, frame))
    if len(text_idx) >= 2:
        out.append(_make_candidate(items, container, text_idx, "cluster", comp, lp, lname, parent_m, l_anim, frame))
    for i, it in enumerate(items):
        if it.get("ty") == "gr":
            m = mat_mul(parent_m, group_matrix(it, frame))
            _walk(it.get("it", []), container + [i], comp, lp, lname, m, l_anim, frame, out)


def _make_candidate(items, container, members, kind, comp, lp, lname, parent_m, l_anim, frame) -> Candidate:
    cid = f"{comp}/L{lp}/" + ".".join(map(str, container + [-1])) + "/" + ",".join(map(str, members))
    cand = Candidate(cid, kind, comp, lp, lname, list(container), list(members))
    boxes_local, boxes_world = [], []
    for gi in members:
        g = items[gi]
        gm = group_matrix(g, frame)
        local_m = gm if kind == "cluster" else IDENTITY
        world_m = mat_mul(parent_m, gm)
        for it in g.get("it", []):
            if it.get("ty") != "sh":
                continue
            val = shape_value_at(it.get("ks", {}), frame)
            if not val or not val.get("v"):
                continue
            cand.n_paths += 1
            cand.n_vertices += len(val["v"])
            if is_animated(it.get("ks")):
                cand.path_animated = True
            boxes_local.append(path_bbox(val, local_m if kind == "cluster" else None))
            boxes_world.append(path_bbox(val, world_m))
        tr = group_transform(g)
        if tr and any(is_animated(tr.get(k)) for k in ("a", "p", "s", "r", "o")):
            cand.group_tr_animated = True
    cand.local_bbox = union_bbox(boxes_local)
    cand.world_bbox = union_bbox(boxes_world)
    cand.fill, cand.stroke = group_style(items[members[0]])
    cand.layer_tr_animated = l_anim
    if cand.path_animated:
        cand.notes.append("هندسه‌ی مسیر کی‌فریم دارد (مورف)؛ در جایگزینی به مسیر ثابت تبدیل می‌شود")
    return cand


def layer_summary(doc: dict) -> list[dict]:
    """فهرست لایه‌ها برای نمایش در رابط کاربری."""
    rows = []
    for comp_id, layers in get_comps(doc).items():
        for lp, layer in enumerate(layers):
            ty = layer.get("ty")
            n_sh = 0
            if ty == 4:
                n_sh = _count_paths(layer.get("shapes", []))
            rows.append({"comp": comp_id, "pos": lp, "ind": layer.get("ind"), "name": layer.get("nm", ""),
                         "type": LAYER_TYPES.get(ty, str(ty)), "paths": n_sh,
                         "parent": layer.get("parent"), "ip": layer.get("ip"), "op": layer.get("op")})
    return rows


def _count_paths(items) -> int:
    n = 0
    for it in items:
        if it.get("ty") == "sh":
            n += 1
        elif it.get("ty") == "gr":
            n += _count_paths(it.get("it", []))
    return n


def template_info(doc: dict) -> dict[str, Any]:
    fr = doc.get("fr", 0) or 0
    ip, op = doc.get("ip", 0), doc.get("op", 0)
    return {"width": doc.get("w"), "height": doc.get("h"), "fps": fr, "ip": ip, "op": op,
            "duration": (op - ip) / fr if fr else None, "version": doc.get("v"),
            "layers": len(doc.get("layers", [])), "assets": len(doc.get("assets", []) or []),
            "name": doc.get("nm", "")}
