"""Filter window for one feature type - like the OS Data Hub's "Advanced Filter Options":
"+ Add rule" (attribute · operator · value), "+ Add group" for a nested set of rules, and
"Match all / any" for each group. The value drop-down lists the values actually found in
the area (from a sample of its features); otherwise the allowed values the API lists, or
values can be typed. For "is one of", picking values from the list adds them one by one.

For OS NGD the CQL that will be sent is shown, and can be written by hand instead.
"""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from ..core import filters as F

HINTS = {"integer": "a whole number", "number": "a number", "date": "YYYY-MM-DD", "date-time": "YYYY-MM-DD",
         "boolean": "true or false", "string": "text"}


class RuleRow(QWidget):
    changed = pyqtSignal()
    removed = pyqtSignal(object)

    def __init__(self, attrs, rule=None, parent=None, values=None):
        super().__init__(parent)
        self.attrs = {a["name"]: a for a in attrs}
        self.values = values      # {attribute: [(text, count)]} found in the area, or None
        self._typed = ""
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.attr = QComboBox()
        self.attr.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.attr.setMinimumContentsLength(12)
        for a in attrs:
            self.attr.addItem(a["title"], a["name"])
            if a.get("description"):
                self.attr.setItemData(self.attr.count() - 1, a["description"], Qt.ItemDataRole.ToolTipRole)
        self.op = QComboBox()
        self.value = QComboBox()
        self.value.setEditable(True)
        self.value.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.value.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.value.setMinimumContentsLength(10)
        self.value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        rm = QToolButton()
        rm.setText("✕")
        rm.setToolTip("Remove this rule")
        rm.clicked.connect(lambda: self.removed.emit(self))
        h.addWidget(self.attr, 3)
        h.addWidget(self.op, 2)
        h.addWidget(self.value, 3)
        h.addWidget(rm)
        self.setMinimumHeight(max(self.attr.sizeHint().height(), self.value.sizeHint().height()))
        if rule:
            if rule["attr"] not in self.attrs:     # kept from before (e.g. the list couldn't be loaded)
                self.attrs[rule["attr"]] = {"name": rule["attr"], "title": rule["attr"], "type": "string", "enum": []}
                self.attr.addItem(rule["attr"], rule["attr"])
            self.attr.setCurrentIndex(self.attr.findData(rule["attr"]))
        self._attr_changed()
        if rule:
            self.op.setCurrentIndex(max(0, self.op.findData(rule["op"])))
            self.value.setEditText(str(rule.get("value") or ""))
        self._typed = self.value.currentText()
        self._op_changed()
        self.value.lineEdit().textEdited.connect(self._edited)
        self.value.activated.connect(self._picked)
        self.attr.currentIndexChanged.connect(lambda _: (self._attr_changed(), self.changed.emit()))
        self.op.currentIndexChanged.connect(lambda _: (self._op_changed(), self.changed.emit()))
        self.value.editTextChanged.connect(lambda _: self.changed.emit())

    def _spec(self):
        return self.attrs.get(self.attr.currentData(), {"type": "string", "enum": []})

    def _attr_changed(self):
        spec = self._spec()
        keep_op, keep_val = self.op.currentData(), self.value.currentText()
        self.op.blockSignals(True)
        self.op.clear()
        for code, label, _ in F.OPERATORS:
            if code in F.TEXT_ONLY and spec["type"] not in ("string", ""):
                continue
            if code in F.ORDERED and spec["type"] in ("boolean",):
                continue
            self.op.addItem(label, code)
        self.op.setCurrentIndex(max(0, self.op.findData(keep_op)))
        self.op.blockSignals(False)
        self.value.blockSignals(True)
        self.value.clear()
        found = (self.values or {}).get(spec.get("name") or self.attr.currentData())
        if found:                               # what's actually in the area
            for text, n in found:
                self.value.addItem(text)
                self.value.setItemData(self.value.count() - 1, f"{n:,} feature(s) in the sample",
                                       Qt.ItemDataRole.ToolTipRole)
            opts = [t for t, _ in found]
        else:
            opts = list(spec.get("enum") or [])
            if spec["type"] == "boolean" and not opts:
                opts = ["true", "false"]
            self.value.addItems(opts)
        self.value.setMaxVisibleItems(20)
        # a different attribute: keep the value only if it still makes sense
        self.value.setEditText(keep_val if (keep_val in opts or not opts) else "")
        self.value.blockSignals(False)
        self._typed = self.value.currentText()
        self._op_changed()

    def _edited(self, text):
        self._typed = text

    def _picked(self, index):
        """Choosing from the list: replaces the value, or for 'is one of' adds to the list."""
        text = self.value.itemText(index)
        if self.op.currentData() == "IN":
            have = F.split_values(self._typed)
            if text not in have:
                have.append(text)
            # ';' between values: OS values can contain commas ('Ambulance, Fire And Police Station')
            text = "; ".join(have) if any("," in v for v in have) or ";" in self._typed else ", ".join(have)
        elif self.op.currentData() == "BETWEEN":
            have = [p.strip() for p in self._typed.split(",") if p.strip()][:1]
            text = ", ".join(have + [text]) if len(have) == 1 else text
        self.value.setEditText(text)
        self._typed = text
        self.changed.emit()

    def _op_changed(self):
        op = self.op.currentData()
        self.value.setVisible(F.NEEDS_VALUE.get(op, True))
        hint = HINTS.get(self._spec()["type"], "text")
        if op == "IN":
            hint = "values, separated by commas (or ; if a value has a comma)"
        elif op == "BETWEEN":
            hint = "from, to   e.g. 5, 20"
        if self.values is not None and not (self.values or {}).get(self.attr.currentData()):
            hint += " (none found in your area)"
        self.value.lineEdit().setPlaceholderText(hint)

    def rule(self):
        return {"attr": self.attr.currentData(), "op": self.op.currentData(),
                "value": self.value.currentText().strip() if F.NEEDS_VALUE.get(self.op.currentData(), True) else ""}


class GroupBox(QFrame):
    changed = pyqtSignal()
    removed = pyqtSignal(object)

    def __init__(self, attrs, flt=None, top=False, parent=None, values=None):
        super().__init__(parent)
        self.attrs = attrs
        self.values = values
        self.top = top
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        if not top:
            self.setFrameShape(QFrame.Shape.StyledPanel)
            self.setStyleSheet("GroupBox { background: palette(alternate-base); }")
        v = QVBoxLayout(self)
        v.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)   # never squash rules - scroll instead
        if top:
            v.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        head.addWidget(QLabel("Match" if top else "Group - match"))
        self.join = QComboBox()
        self.join.addItem("all of these (and)", "AND")
        self.join.addItem("any of these (or)", "OR")
        self.join.currentIndexChanged.connect(lambda _: self.changed.emit())
        head.addWidget(self.join)
        head.addStretch(1)
        if not top:
            rm = QToolButton()
            rm.setText("✕")
            rm.setToolTip("Remove this group")
            rm.clicked.connect(lambda: self.removed.emit(self))
            head.addWidget(rm)
        v.addLayout(head)
        self.rows = QVBoxLayout()
        v.addLayout(self.rows)
        foot = QHBoxLayout()
        self.add_rule_btn = QPushButton("+ Add rule")
        self.add_rule_btn.clicked.connect(lambda: self.add_rule())
        foot.addWidget(self.add_rule_btn)
        if top:
            self.add_group_btn = QPushButton("+ Add group")
            self.add_group_btn.setToolTip("A set of rules that is worked out together, e.g. (A and B) or C")
            self.add_group_btn.clicked.connect(lambda: self.add_group())
            foot.addWidget(self.add_group_btn)
        foot.addStretch(1)
        v.addLayout(foot)
        self.set_filter(flt)

    def items(self):
        return [self.rows.itemAt(i).widget() for i in range(self.rows.count())]

    def add_rule(self, rule=None):
        row = RuleRow(self.attrs, rule, values=self.values)
        row.changed.connect(self.changed)
        row.removed.connect(self._remove)
        self.rows.addWidget(row)
        self.changed.emit()
        return row

    def add_group(self, flt=None):
        grp = GroupBox(self.attrs, flt or {"join": "OR", "items": [{}]}, values=self.values)
        grp.changed.connect(self.changed)
        grp.removed.connect(self._remove)
        self.rows.addWidget(grp)
        self.changed.emit()
        return grp

    def _remove(self, w):
        self.rows.removeWidget(w)
        w.setParent(None)
        w.deleteLater()
        self.changed.emit()

    def set_filter(self, flt):
        for w in self.items():
            self._remove(w)
        flt = flt or {"join": "AND", "items": []}
        self.join.setCurrentIndex(max(0, self.join.findData((flt.get("join") or "AND").upper())))
        for it in flt.get("items", []):
            if F.is_group(it) and self.top:
                self.add_group(it)
            elif F.is_group(it):            # only one level of groups, like the OS Data Hub
                for r in F.rules(it):
                    self.add_rule(r)
            else:
                self.add_rule(it or None)

    def filter(self):
        out = []
        for w in self.items():
            if isinstance(w, GroupBox):
                sub = w.filter()
                if sub["items"]:
                    out.append(sub)
            elif w.attr.currentData():
                out.append(w.rule())
        return {"join": self.join.currentData(), "items": out}


class FilterDialog(QDialog):
    """``attrs``: list from filters.parse_queryables / parse_describe_feature_type.
    ``current``: what FeaturesTab keeps per feature type - {'filter', 'cql'} or None."""

    def __init__(self, title, attrs, kind, current=None, note="", parent=None, values=None, values_note=""):
        super().__init__(parent)
        self.values = values
        self.kind = kind
        self.attrs = attrs
        self.types = {a["name"]: a["type"] for a in attrs}
        self.titles = {a["name"]: a["title"] for a in attrs}
        self.result_value = None
        self.setWindowTitle(f"Filter - {title}")
        self.resize(700, 580)
        current = current or {}
        v = QVBoxLayout(self)
        intro = QLabel(f"Only download <b>{title}</b> features that match these rules (and are in your area).")
        intro.setWordWrap(True)
        v.addWidget(intro)
        if note:
            n = QLabel(note)
            n.setWordWrap(True)
            n.setStyleSheet("color: #b35806;")
            v.addWidget(n)
        if values_note:
            vn = QLabel(values_note)
            vn.setWordWrap(True)
            vn.setStyleSheet("color: palette(mid);" if not values else "")
            v.addWidget(vn)
        self.values_label = vn if values_note else None
        self.group = GroupBox(attrs, current.get("filter") or {"join": "AND", "items": [{}] if attrs else []}, top=True,
                              values=values)
        self.group.changed.connect(self._update)
        holder = QWidget()
        hv = QVBoxLayout(holder)
        hv.addWidget(self.group)
        hv.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        v.addWidget(scroll, 1)

        self.own = None
        if kind == "ngd":
            self.own = QCheckBox("Write the query myself (CQL)")
            self.own.setToolTip("e.g.  description = 'Building' AND height_absolutemax_m > 15\n"
                                "Operators: = <> < <= > >= LIKE IN BETWEEN IS NULL AND OR NOT")
            self.own.toggled.connect(self._own_toggled)
            v.addWidget(self.own)
        self.preview = QPlainTextEdit()
        self.preview.setMaximumHeight(70)
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("No filter - every feature in the area is downloaded.")
        v.addWidget(self.preview)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c0392b;")
        v.addWidget(self.error)

        bb = QDialogButtonBox()
        self.clear_btn = bb.addButton("Clear all filters", QDialogButtonBox.ButtonRole.ResetRole)
        self.clear_btn.clicked.connect(self.clear)
        bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.apply_btn = bb.addButton("Apply filter", QDialogButtonBox.ButtonRole.AcceptRole)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.apply)
        v.addWidget(bb)
        if self.own is not None and current.get("cql"):
            self.own.setChecked(True)
            self.preview.setPlainText(current["cql"])
        self._update()

    # ------------------------------------------------------------ preview
    def _own_toggled(self, on):
        self.group.setEnabled(not on)
        self.preview.setReadOnly(not on)
        if not on:
            self._update()

    def _build(self):
        """(filter dict, where string, summary) or raises FilterError."""
        if self.own is not None and self.own.isChecked():
            cql = self.preview.toPlainText().strip()
            return None, cql, cql, cql
        flt = self.group.filter()
        where = F.to_cql(flt, self.types) if self.kind == "ngd" else F.to_ogc(flt, self.types)
        return flt, where, F.describe(flt, self.titles), None

    def _update(self):
        if self.own is not None and self.own.isChecked():
            return
        try:
            flt, where, text, _ = self._build()
            self.error.clear()
            self.preview.setPlainText(where if self.kind == "ngd" else text)
        except F.FilterError as ex:
            self.error.setText(str(ex))
        except Exception as ex:     # never fail silently - say what went wrong
            self.error.setText(f"Couldn't build the filter: {ex!r}")

    # ------------------------------------------------------------ buttons
    def clear(self):
        if self.own is not None:
            self.own.setChecked(False)
        self.group.set_filter({"join": "AND", "items": []})
        self._update()

    def apply(self):
        try:
            flt, where, text, cql = self._build()
        except F.FilterError as ex:
            self.error.setText(str(ex))
            return
        except Exception as ex:
            self.error.setText(f"Couldn't build the filter: {ex!r}")
            return
        if not where:
            self.result_value = None          # no rules = no filter
        else:
            self.result_value = {"filter": flt, "cql": cql, "where": where, "text": text}
        self.accept()
