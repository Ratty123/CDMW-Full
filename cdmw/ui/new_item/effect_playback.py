"""Compact controls for the resident effect simulation."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QGridLayout, QHBoxLayout, QPushButton, QDoubleSpinBox, QSpinBox, QComboBox, QLabel, QSizePolicy


class EffectPlaybackControls(QWidget):
    def __init__(self, placement):
        super().__init__(placement)
        self.setObjectName('effect_playback_controls')
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.placement = placement
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        restart = QPushButton('Restart')
        restart.setToolTip('Replay the effect from the beginning.')
        restart.clicked.connect(self.restart)
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.05, 4.0)
        self.speed.setValue(1.0)
        self.speed.setSuffix('×')
        self.speed.setToolTip('Preview playback speed; exported simulation settings are unchanged.')
        self.speed.valueChanged.connect(lambda v: self.send(speed=v))
        seek = QWidget()
        seek_row = QHBoxLayout(seek)
        seek_row.setContentsMargins(0, 0, 0, 0)
        seek_row.setSpacing(4)
        seek_row.addWidget(QLabel('Seek'))
        self.time = QDoubleSpinBox()
        self.time.setRange(0, 3600)
        self.time.setDecimals(2)
        self.time.setSingleStep(0.05)
        self.time.setSuffix(' s')
        self.time.editingFinished.connect(self.seek)
        seek_row.addWidget(self.time)
        self.seed = QSpinBox()
        self.seed.setRange(0, 9999)
        self.seed.setPrefix('Seed ')
        self.seed.setToolTip('Repeatable random seed for comparing effects.')
        self.seed.valueChanged.connect(lambda v: self.send(seed=v))
        self.quality = QComboBox()
        for name, budget in (('Draft', 64), ('Normal', 256), ('High', 1024), ('Ultra', 2048)):
            self.quality.addItem(name, budget)
        self.quality.setCurrentIndex(1)
        self.quality.setToolTip('Preview particle limit per emitter; the whole scene remains limited to 32,768 drawing instances.')
        self.quality.currentIndexChanged.connect(lambda _: self.send(quality=self.quality.currentData()))
        self._controls = (restart, self.speed, seek, self.seed, self.quality)
        self._columns = 0
        for control in self._controls:
            control.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._reflow(self.width())
        self.setEnabled(callable(getattr(placement.host, 'set_effect_preview_controls', None)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow(event.size().width())

    def _reflow(self, width):
        layout = self.layout()
        required = sum(control.sizeHint().width() for control in self._controls) + 4 * (len(self._controls) - 1)
        columns = len(self._controls) if width >= required else 3
        if columns == self._columns:
            return
        self._columns = columns
        while layout.count():
            layout.takeAt(0)
        for column in range(len(self._controls) + 1):
            layout.setColumnStretch(column, 1 if column == columns else 0)
        for index, control in enumerate(self._controls):
            layout.addWidget(control, index // columns, index % columns, Qt.AlignmentFlag.AlignLeft)
        self.updateGeometry()

    def send(self, **values):
        host = self.placement.host
        setter = getattr(host, 'set_effect_preview_controls', None)
        if callable(setter):
            setter(**values)

    def restart(self):
        self.time.setValue(0)
        self.send(time_seconds=0)
        self.placement.pause_button.setChecked(False)

    def seek(self):
        self.placement.pause_button.setChecked(True)
        self.send(time_seconds=self.time.value())
