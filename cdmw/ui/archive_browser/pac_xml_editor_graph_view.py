"""Accessible pannable/zoomable PAC XML connection graph widget."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QBrush, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.pac_xml_graph import PacXmlConnectionGraph, PacXmlGraphNode


class _NodeItem(QGraphicsRectItem):
    def __init__(self, node: PacXmlGraphNode, callback: Callable[[PacXmlGraphNode], None]) -> None:
        super().__init__(QRectF(0, 0, 220, 62))
        self.node = node
        self._callback = callback
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        status_color = QColor("#2f855a") if node.status == "resolved" else QColor("#b7791f") if node.status == "index warming" else QColor("#8b5cf6") if node.kind in {"sidecar", "submesh"} else QColor("#9b2c2c")
        self.setPen(QPen(status_color, 2))
        self.setBrush(QBrush(QColor("#202733")))
        label = QGraphicsSimpleTextItem(node.label, self)
        label.setBrush(QBrush(QColor("#f3f4f6")))
        label.setPos(9, 7)
        detail = node.path or node.evidence
        if len(detail) > 42:
            detail = "…" + detail[-41:]
        detail_item = QGraphicsSimpleTextItem(detail, self)
        detail_item.setBrush(QBrush(QColor("#aeb8c7")))
        detail_item.setPos(9, 31)
        self.setToolTip(
            "\n".join(part for part in (node.path, f"Status: {node.status}", f"Confidence: {node.confidence}", node.evidence) if part)
        )

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._callback(self.node)
        super().mouseDoubleClickEvent(event)


class _ZoomableGraphView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, parent: QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self.setObjectName("PacXmlConnectionGraphicsView")
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    def wheelEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        event.accept()


class PacXmlConnectionGraphView(QWidget):
    parameterRequested = Signal(str)
    entryPreviewRequested = Signal(object)
    refreshRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PacXmlConnectionsTab")
        self._graph = PacXmlConnectionGraph((), ())
        self._nodes_by_id: dict[str, PacXmlGraphNode] = {}
        self._node_items: dict[str, _NodeItem] = {}
        self._list_items: dict[str, QTreeWidgetItem] = {}
        self._edge_list_items: dict[str, QTreeWidgetItem] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        header = QHBoxLayout()
        self.status_label = QLabel("Connections have not been resolved yet.")
        self.status_label.setObjectName("HintLabel")
        self.status_label.setWordWrap(True)
        self.fit_button = QPushButton("Fit Graph")
        self.fit_button.setObjectName("PacXmlGraphFitButton")
        self.refresh_button = QPushButton("Refresh from Current Indexes")
        self.refresh_button.setObjectName("PacXmlGraphRefreshButton")
        self.refresh_button.setToolTip("Reuses existing archive indexes and Asset Family evidence; it never starts a global scan.")
        header.addWidget(self.status_label, 1)
        header.addWidget(self.fit_button)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Vertical)
        self.scene = QGraphicsScene(self)
        self.graphics_view = _ZoomableGraphView(self.scene)
        splitter.addWidget(self.graphics_view)
        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.addWidget(QLabel("Keyboard-accessible connection list (Enter or double-click previews a resolved file):"))
        self.list_tree = QTreeWidget()
        self.list_tree.setObjectName("PacXmlConnectionList")
        self.list_tree.setColumnCount(5)
        self.list_tree.setHeaderLabels(["Kind", "File / Node", "Status", "Confidence", "Evidence"])
        self.list_tree.setRootIsDecorated(False)
        self.list_tree.setAlternatingRowColors(True)
        self.list_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        details_layout.addWidget(self.list_tree)
        self.details_label = QLabel("Select a node or labelled parameter edge for details.")
        self.details_label.setObjectName("PacXmlConnectionDetails")
        self.details_label.setWordWrap(True)
        details_layout.addWidget(self.details_label)
        splitter.addWidget(details)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self.fit_button.clicked.connect(self.fit_graph)
        self.refresh_button.clicked.connect(self.refreshRequested.emit)
        self.scene.selectionChanged.connect(self._scene_selection_changed)
        self.list_tree.currentItemChanged.connect(self._list_selection_changed)
        self.list_tree.itemActivated.connect(lambda item, _column: self._preview_list_item(item))

    @property
    def graph(self) -> PacXmlConnectionGraph:
        return self._graph

    def set_graph(self, graph: PacXmlConnectionGraph) -> None:
        self._graph = graph
        self._nodes_by_id = graph.node_by_id()
        self._node_items.clear()
        self._list_items.clear()
        self._edge_list_items.clear()
        self.scene.clear()
        self.list_tree.clear()
        lane_counts: dict[int, int] = defaultdict(int)
        positions: dict[str, QPointF] = {}
        for node in graph.nodes:
            lane_index = lane_counts[node.lane]
            lane_counts[node.lane] += 1
            position = QPointF(node.lane * 285.0, lane_index * 92.0)
            positions[node.node_id] = position
            node_item = _NodeItem(node, self._preview_node)
            node_item.setPos(position)
            self.scene.addItem(node_item)
            self._node_items[node.node_id] = node_item
            list_item = QTreeWidgetItem([node.kind, node.label, node.status, node.confidence, node.evidence])
            list_item.setData(0, Qt.UserRole, node.node_id)
            list_item.setToolTip(1, node.path)
            list_item.setToolTip(4, node.evidence)
            self.list_tree.addTopLevelItem(list_item)
            self._list_items[node.node_id] = list_item

        for edge in graph.edges:
            source = positions.get(edge.source_id)
            target = positions.get(edge.target_id)
            if source is None or target is None:
                continue
            start = source + QPointF(220.0, 31.0)
            end = target + QPointF(0.0, 31.0)
            line = QGraphicsLineItem(start.x(), start.y(), end.x(), end.y())
            line.setPen(QPen(QColor("#718096"), 1.5))
            line.setZValue(-1)
            line.setFlag(QGraphicsItem.ItemIsSelectable, bool(edge.row_id))
            line.setData(0, edge.row_id)
            line.setData(1, edge.label)
            line.setData(2, edge.evidence)
            line.setToolTip("\n".join(part for part in (edge.label, edge.confidence, edge.evidence) if part))
            self.scene.addItem(line)
            if edge.row_id:
                edge_item = QTreeWidgetItem(
                    ["parameter edge", edge.label, "source", edge.confidence, edge.evidence]
                )
                edge_item.setData(0, Qt.UserRole + 1, edge.row_id)
                edge_item.setData(0, Qt.UserRole + 2, edge.target_id)
                edge_item.setToolTip(1, "Select to locate this exact parameter row.")
                self.list_tree.addTopLevelItem(edge_item)
                self._edge_list_items[edge.row_id] = edge_item
            if edge.label:
                label = QGraphicsSimpleTextItem(edge.label)
                label.setBrush(QBrush(QColor("#cbd5e0")))
                label.setPos((start.x() + end.x()) / 2 - 25, (start.y() + end.y()) / 2 - 18)
                label.setToolTip(line.toolTip())
                self.scene.addItem(label)

        state = "index warming" if graph.index_warming else "current indexes"
        self.status_label.setText(
            f"{graph.texture_path_count} unique XML asset path(s); {graph.unresolved_path_count} unresolved using {state}. "
            "The graph is navigation-only."
        )
        for column, width in enumerate((105, 260, 100, 115, 360)):
            self.list_tree.setColumnWidth(column, width)
        self.fit_graph()

    def fit_graph(self) -> None:
        bounds = self.scene.itemsBoundingRect()
        if not bounds.isEmpty():
            self.graphics_view.fitInView(bounds.adjusted(-20, -20, 20, 20), Qt.KeepAspectRatio)

    def select_parameter_edge(self, row_id: str) -> None:
        for item in self.scene.items():
            if isinstance(item, QGraphicsLineItem) and str(item.data(0) or "") == row_id:
                item.setSelected(True)
                self.graphics_view.ensureVisible(item)
                return

    def _preview_node(self, node: PacXmlGraphNode) -> None:
        if node.resolved_entry is not None:
            self.entryPreviewRequested.emit(node.resolved_entry)

    def _preview_list_item(self, item: QTreeWidgetItem) -> None:
        row_id = str(item.data(0, Qt.UserRole + 1) or "")
        if row_id:
            self.parameterRequested.emit(row_id)
            return
        node = self._nodes_by_id.get(str(item.data(0, Qt.UserRole) or ""))
        if node is not None:
            self._preview_node(node)

    def _scene_selection_changed(self) -> None:
        selected = self.scene.selectedItems()
        if not selected:
            return
        item = selected[0]
        if isinstance(item, _NodeItem):
            node = item.node
            self.details_label.setText(
                "\n".join(part for part in (node.path or node.label, f"Status: {node.status}", f"Confidence: {node.confidence}", node.evidence) if part)
            )
            list_item = self._list_items.get(node.node_id)
            if list_item is not None:
                self.list_tree.setCurrentItem(list_item)
        elif isinstance(item, QGraphicsLineItem):
            row_id = str(item.data(0) or "")
            self.details_label.setText(f"Parameter edge: {item.data(1)}\n{item.data(2)}")
            if row_id:
                edge_item = self._edge_list_items.get(row_id)
                if edge_item is not None:
                    blocker = QSignalBlocker(self.list_tree)
                    self.list_tree.setCurrentItem(edge_item)
                    del blocker
                self.parameterRequested.emit(row_id)

    def _list_selection_changed(self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None) -> None:
        if current is None:
            return
        row_id = str(current.data(0, Qt.UserRole + 1) or "")
        if row_id:
            self.details_label.setText(f"Parameter edge: {current.text(1)}\n{current.text(4)}")
            self.parameterRequested.emit(row_id)
            return
        node_id = str(current.data(0, Qt.UserRole) or "")
        node = self._nodes_by_id.get(node_id)
        if node is None:
            return
        self.details_label.setText(
            "\n".join(part for part in (node.path or node.label, f"Status: {node.status}", f"Confidence: {node.confidence}", node.evidence) if part)
        )
        node_item = self._node_items.get(node_id)
        if node_item is not None and not node_item.isSelected():
            node_item.setSelected(True)
            self.graphics_view.ensureVisible(node_item)


__all__ = ["PacXmlConnectionGraphView"]
