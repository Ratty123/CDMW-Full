"""Compact controls for the resident effect simulation."""
from PySide6.QtWidgets import QWidget, QGridLayout, QPushButton, QDoubleSpinBox, QSpinBox, QComboBox, QLabel


class EffectPlaybackControls(QWidget):
    def __init__(self, placement):
        super().__init__(placement)
        self.placement = placement
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        restart = QPushButton('Restart')
        restart.setToolTip('Replay the effect from the beginning.')
        restart.clicked.connect(self.restart)
        layout.addWidget(restart, 0, 0)
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.05, 4.0)
        self.speed.setValue(1.0)
        self.speed.setSuffix('×')
        self.speed.setToolTip('Preview playback speed; exported simulation settings are unchanged.')
        self.speed.valueChanged.connect(lambda v: self.send(speed=v))
        layout.addWidget(self.speed, 0, 1)
        layout.addWidget(QLabel('Seek'), 0, 2)
        self.time = QDoubleSpinBox()
        self.time.setRange(0, 3600)
        self.time.setDecimals(2)
        self.time.setSingleStep(0.05)
        self.time.setSuffix(' s')
        self.time.editingFinished.connect(self.seek)
        layout.addWidget(self.time, 0, 3)
        self.seed = QSpinBox()
        self.seed.setRange(0, 9999)
        self.seed.setPrefix('Seed ')
        self.seed.setToolTip('Repeatable random seed for comparing effects.')
        self.seed.valueChanged.connect(lambda v: self.send(seed=v))
        layout.addWidget(self.seed, 1, 0, 1, 2)
        self.quality = QComboBox()
        for name, budget in (('Draft', 64), ('Normal', 256), ('High', 1024), ('Ultra', 2048)):
            self.quality.addItem(name, budget)
        self.quality.setCurrentIndex(1)
        self.quality.setToolTip('Preview particle limit per emitter; the whole scene remains limited to 32,768 drawing instances.')
        self.quality.currentIndexChanged.connect(lambda _: self.send(quality=self.quality.currentData()))
        layout.addWidget(self.quality, 1, 2, 1, 2)
        self.setEnabled(callable(getattr(placement.host, 'set_effect_preview_controls', None)))

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
