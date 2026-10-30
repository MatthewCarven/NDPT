"""The settings tab: how both tabs probe."""

from __future__ import annotations

import dataclasses
import socket

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ndpt.cli import MIN_INTERVAL
from ndpt.core.session import MAX_PAYLOAD
from ndpt.gui.bridge import Settings
from ndpt.gui.theme import Theme

FAMILIES = (("IPv4 or IPv6, whichever the name gives first", socket.AF_UNSPEC),
            ("IPv4 only", socket.AF_INET), ("IPv6 only", socket.AF_INET6))
PROTOCOLS = (("ICMP echo: pings and traces", "icmp"),
             ("TCP handshake: pings only, TCP can't trace", "tcp"))
TCP_NOTE = ("TCP can't trace: a TCP connect can't set the probe's TTL, so no router on the way ever "
            "answers. While TCP is chosen, the Trace tab says so and the Ping tab times handshakes "
            "to the port.")


class SettingsView(QWidget):
    """A form over `Settings`. Apply sends the new settings; the window restarts the probes."""

    applied = Signal(object)  # a Settings

    def __init__(self, settings: Settings, theme: Theme, demo: bool = False) -> None:
        super().__init__()
        self.current = settings
        self.demo = demo
        self.interval = QDoubleSpinBox(decimals=2, singleStep=0.1, suffix=" s")
        self.interval.setRange(0.01 if demo else MIN_INTERVAL, 60.0)
        self.interval.setToolTip("Time between probes to each host, and between trace rounds")
        self.timeout = QDoubleSpinBox(decimals=2, singleStep=0.1, suffix=" s")
        self.timeout.setRange(0.1, 30.0)
        self.timeout.setToolTip("How long to wait for each answer before counting it lost")
        self.size = QSpinBox(suffix=" bytes")
        self.size.setRange(0, MAX_PAYLOAD)
        self.size.setToolTip("Payload size; Windows ping sends 32")
        self.max_hops = QSpinBox()
        self.max_hops.setRange(1, 255)
        self.family = QComboBox()
        for label, family in FAMILIES:
            self.family.addItem(label, family)
        self.protocol = QComboBox()
        for label, protocol in PROTOCOLS:
            self.protocol.addItem(label, protocol)
        self.protocol.currentIndexChanged.connect(self._protocol_changed)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setToolTip("An open port: 443, 80 or 22. A closed one still answers, but Windows "
                             "retries the connect after the reset, so its times read high.")
        self.lookup_names = QCheckBox("Look up router names in a trace")
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setStyleSheet(f"color: {theme.critical};")

        protocol_row = QHBoxLayout()
        protocol_row.addWidget(self.protocol, 1)
        protocol_row.addWidget(QLabel("port"))
        protocol_row.addWidget(self.port)
        form = QFormLayout()
        form.addRow("Interval", self.interval)
        form.addRow("Timeout", self.timeout)
        form.addRow("Payload", self.size)
        form.addRow("Max hops (trace)", self.max_hops)
        form.addRow("Addresses", self.family)
        form.addRow("Probe with", protocol_row)
        form.addRow("", self.note)
        form.addRow("", self.lookup_names)

        self.apply_button = QPushButton("Apply")
        self.apply_button.setToolTip("Restarts the probes on both tabs with these settings")
        self.apply_button.clicked.connect(self.apply)
        self.revert_button = QPushButton("Revert")
        self.revert_button.clicked.connect(lambda: self.load(self.current))
        buttons = QHBoxLayout()
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.revert_button)
        buttons.addStretch(1)
        fields = QWidget()
        fields.setLayout(form)
        fields.setMaximumWidth(720)  # a form, not a banner across the window
        layout = QVBoxLayout(self)
        layout.addWidget(fields)
        layout.addWidget(QLabel("Apply restarts the probes on both tabs, so their numbers start again."))
        layout.addLayout(buttons)
        layout.addWidget(self.message)
        layout.addStretch(1)
        if demo:
            self.protocol.setEnabled(False)
            self.port.setEnabled(False)
            self.protocol.setToolTip("The demo network sends nothing, so the protocol doesn't apply")
        self.load(settings)

    def load(self, settings: Settings) -> None:
        self.interval.setValue(settings.interval)
        self.timeout.setValue(settings.timeout)
        self.size.setValue(settings.size)
        self.max_hops.setValue(settings.max_hops)
        self.family.setCurrentIndex(max(0, self.family.findData(settings.family)))
        self.protocol.setCurrentIndex(max(0, self.protocol.findData(settings.protocol)))
        self.port.setValue(settings.port)
        self.lookup_names.setChecked(settings.lookup_names)
        self.message.clear()
        self._protocol_changed()

    def settings(self) -> Settings:
        """What the form says now (not yet applied)."""
        return dataclasses.replace(
            self.current, interval=round(self.interval.value(), 2), timeout=round(self.timeout.value(), 2),
            size=self.size.value(), max_hops=self.max_hops.value(), family=self.family.currentData(),
            protocol=self.protocol.currentData(), port=self.port.value(),
            lookup_names=self.lookup_names.isChecked())

    def apply(self) -> None:
        self.message.clear()
        self.applied.emit(self.settings())

    def accepted(self, settings: Settings) -> None:
        """The window took these settings."""
        self.current = settings

    def refused(self, why: str) -> None:
        self.message.setText(why)

    def _protocol_changed(self) -> None:
        tcp = self.protocol.currentData() == "tcp"
        self.port.setEnabled(tcp and not self.demo)
        if self.demo:
            self.note.setText("The demo network sends nothing, so the protocol doesn't apply.")
        else:
            self.note.setText(TCP_NOTE if tcp else "")
        self.note.setVisible(bool(self.note.text()))
