"""The drawings of EAGLA, as SVG text: the correlation circles, the flow diagram of a class of
transactions and its monthly bars. Every text that reaches the drawing goes through ``esc``."""
from ._js import js_sum
from .eagla_correlation import radii
from .scot_flows import node_label

YELLOW, ORANGE, BLUE = "#f2c94c", "#f2994a", "#56a0d3"
BAND, UNUSUAL, NODE = "#9aa5b1", "#d64545", "#34495e"


def esc(text):
    return (
        str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")
    )


def spaced(value):
    """A whole amount with a space between thousands."""
    return "{:,.0f}".format(value or 0).replace(",", " ")


def _num(value):
    return ("%.1f" % value).rstrip("0").rstrip(".")


def _svg(width, height, body, label):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" class="o_ea_eagla_svg" viewBox="0 0 %d %d" width="100%%" '
        'style="max-width:%dpx" role="img" aria-label="%s">%s</svg>' % (width, height, width, esc(label), "".join(body))
    )


def _circle(x, y, r, color):
    return '<circle cx="%s" cy="%s" r="%s" fill="%s" fill-opacity="0.65" stroke="%s"/>' % (_num(x), _num(y), _num(r), color, color)


def _text(x, y, text, size=11, anchor="start", weight="normal"):
    return '<text x="%s" y="%s" font-size="%d" text-anchor="%s" font-weight="%s" fill="currentColor">%s</text>' % (
        _num(x), _num(y), size, anchor, weight, esc(text),
    )


def _legend(x, y, items):
    body = []
    for position, (color, text) in enumerate(items):
        top = y + position * 20
        body.append('<rect x="%s" y="%s" width="12" height="12" fill="%s" fill-opacity="0.65" stroke="%s"/>' % (_num(x), _num(top), color, color))
        body.append(_text(x + 18, top + 10, text))
    return body


def two_way_svg(denominator_total, numerator_total, middle_text, legend, label):
    """Two overlapping circles: the denominator (yellow) and the numerator (orange), their areas
    after the yearly totals, the yearly average in the middle."""
    r_den, r_num = radii([denominator_total, numerator_total])
    cy = 90
    cx_den = 20 + r_den
    cx_num = cx_den + (r_den + r_num) * 0.6
    middle = ((cx_num - r_num) + (cx_den + r_den)) / 2
    body = [_circle(cx_den, cy, r_den, YELLOW), _circle(cx_num, cy, r_num, ORANGE), _text(middle, cy + 4, middle_text, 13, "middle", "bold")]
    body += _legend(max(cx_num + r_num, cx_den + r_den) + 30, 60, [(YELLOW, legend[0]), (ORANGE, legend[1])])
    return _svg(560, 180, body, label)


def three_way_svg(totals, legend, label):
    """Three overlapping circles: A yellow, B orange, C blue, their areas after the yearly totals."""
    r_a, r_b, r_c = radii(totals, largest=60.0)
    top = max(r_a, r_b)
    xa, y = 20 + r_a, 20 + top
    xb = xa + 0.65 * (r_a + r_b)
    xc, yc = (xa + xb) / 2, y + 0.6 * (top + r_c)
    body = [_circle(xa, y, r_a, YELLOW), _circle(xb, y, r_b, ORANGE), _circle(xc, yc, r_c, BLUE)]
    body += [_text(xa, y + 4, "A", 13, "middle", "bold"), _text(xb, y + 4, "B", 13, "middle", "bold"), _text(xc, yc + 4, "C", 13, "middle", "bold")]
    body += _legend(max(xb + r_b, xc + r_c, xa + r_a) + 30, 60, [(YELLOW, legend[0]), (ORANGE, legend[1]), (BLUE, legend[2])])
    return _svg(560, int(yc + r_c + 12), body, label)


def flow_svg(result, locale, entry_words, label):
    """The flow diagram of a class: one column of nodes per stage, a band per flow as wide as
    its amount, the unusual ones in red. ``entry_words``: "entry" and "entries" in the screen's
    language."""
    width, height, top, gap, node_w = 780, 380, 30, 26, 12
    xs = [170, 370, 560]
    columns = result["columns"]
    throughput = {node["key"]: max(node["in"], node["out"]) for node in result["nodes"]}
    sums = [js_sum((throughput[key] for key in column), 0.0) for column in columns]
    most = max([len(column) for column in columns] + [1])
    usable = height - top - 20 - gap * (most - 1)
    scale = usable / max(sums + [1.0])
    place = {}
    for index, column in enumerate(columns):
        y = top
        for key in column:
            h = max(throughput[key] * scale, 3.0)
            place[key] = {"x": xs[index], "y": y, "h": h, "col": index, "in": 0.0, "out": 0.0}
            y += h + gap
    body = []
    for key, node in place.items():
        body.append('<rect x="%s" y="%s" width="%d" height="%s" fill="%s"><title>%s</title></rect>' % (
            _num(node["x"]), _num(node["y"]), node_w, _num(node["h"]), NODE, esc(node_label(key, locale)),
        ))
        if node["col"] == 0:
            body.append(_text(node["x"] - 6, node["y"] + 12, node_label(key, locale), 11, "end", "bold"))
        elif node["col"] == 2:
            body.append(_text(node["x"] + node_w + 6, node["y"] + 12, node_label(key, locale), 11, "start", "bold"))
        else:
            body.append(_text(node["x"] + node_w / 2, node["y"] - 6, node_label(key, locale), 11, "middle", "bold"))
    flows = sorted(
        (flow for flow in result["flows"] if flow["source"] in place and flow["target"] in place),
        key=lambda flow: (place[flow["source"]]["col"], place[flow["source"]]["y"], place[flow["target"]]["col"], place[flow["target"]]["y"]),
    )
    labels = []
    for flow in flows:
        source, target = place[flow["source"]], place[flow["target"]]
        thick = flow["amount"] * scale
        w = max(thick, 2.0 if flow["unusual"] else 1.5)
        sy = source["y"] + source["out"] + w / 2
        ty = target["y"] + target["in"] + w / 2
        source["out"] += thick
        target["in"] += thick
        sx, tx = source["x"] + node_w, target["x"]
        bend = max(60.0, abs(tx - sx) / 2)
        color, opacity = (UNUSUAL, "0.9") if flow["unusual"] else (BAND, "0.55")
        text = "%s · %d %s" % (spaced(flow["amount"]), flow["entries"], entry_words[0] if flow["entries"] == 1 else entry_words[1])
        body.append(
            '<path d="M%s %s C%s %s %s %s %s %s" fill="none" stroke="%s" stroke-opacity="%s" stroke-width="%s"><title>%s</title></path>' % (
                _num(sx), _num(sy), _num(sx + bend), _num(sy), _num(tx - bend), _num(ty), _num(tx), _num(ty),
                color, opacity, _num(w), esc("%s → %s: %s" % (node_label(flow["source"], locale), node_label(flow["target"], locale), text)),
            )
        )
        labels.append(_text((sx + tx) / 2, (sy + ty) / 2 - 3, text, 10, "middle"))
    return _svg(width, height, body + labels, label)


def timing_svg(entering, leaving, months, legend, label):
    """Monthly bars side by side: entering the middle account (orange), leaving it (blue)."""
    width, height, left, bottom = 780, 210, 20, 30
    top_value = max(list(entering) + list(leaving) + [1.0])
    usable = height - bottom - 30
    step = (width - left * 2) / 12.0
    body = []
    for index in range(12):
        x = left + index * step + step * 0.15
        for offset, (values, color) in enumerate(((entering, ORANGE), (leaving, BLUE))):
            h = values[index] / top_value * usable if values[index] > 0 else 0
            body.append('<rect x="%s" y="%s" width="%s" height="%s" fill="%s"><title>%s</title></rect>' % (
                _num(x + offset * step * 0.35), _num(height - bottom - h), _num(step * 0.33), _num(h), color,
                esc("%s: %s" % (legend[offset], spaced(values[index]))),
            ))
        body.append(_text(left + index * step + step / 2, height - bottom + 16, months[index], 11, "middle"))
    body += _legend(left, 4, [(ORANGE, legend[0])])
    body += _legend(left + 330, 4, [(BLUE, legend[1])])
    return _svg(width, height, body, label)
