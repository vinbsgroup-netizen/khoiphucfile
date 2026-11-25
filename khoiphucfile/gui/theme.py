"""Màu sắc và kiểu dáng chung, theo chế độ sáng/tối của hệ điều hành."""

from __future__ import annotations

import os
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


HERE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")


@dataclass(frozen=True)
class Tokens:
    window: str
    rail: str
    base: str
    hover: str
    text: str
    muted: str
    line: str
    accent: str
    accent_hover: str
    accent_text: str
    accent_soft: str
    info_bg: str
    info_fg: str
    ok_bg: str
    ok_fg: str
    warn_bg: str
    warn_fg: str
    error_bg: str
    error_fg: str


LIGHT = Tokens(window="#F4F6FA", rail="#E6EBF4", base="#FFFFFF", hover="#EDF1F8", text="#14213A", muted="#55627A",
               line="#D0D8E5", accent="#0B4FD6", accent_hover="#0940B0", accent_text="#FFFFFF", accent_soft="#D9E6FC",
               info_bg="#E2ECFB", info_fg="#16407F", ok_bg="#DDF3EC", ok_fg="#0E5C47", warn_bg="#FDF1D6", warn_fg="#704800",
               error_bg="#FBE4E1", error_fg="#8E1F14")
DARK = Tokens(window="#0F1626", rail="#0A101D", base="#172036", hover="#1F2A44", text="#E4EAF5", muted="#94A3BF",
              line="#2C3A58", accent="#3D9BFF", accent_hover="#5FAEFF", accent_text="#04162E", accent_soft="#16315F",
              info_bg="#14294A", info_fg="#A9CEFF", ok_bg="#0F302C", ok_fg="#7CE3C6", warn_bg="#372C13", warn_fg="#F0CD83",
              error_bg="#3B1F1C", error_fg="#FFB3A9")


def current() -> Tokens:
    dark = QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    return DARK if dark else LIGHT


def apply(app: QApplication) -> None:
    tokens = current()
    palette = QPalette()
    for role, color in ((QPalette.Window, tokens.window), (QPalette.WindowText, tokens.text),
                        (QPalette.Base, tokens.base), (QPalette.AlternateBase, tokens.hover),
                        (QPalette.Text, tokens.text), (QPalette.Button, tokens.base),
                        (QPalette.ButtonText, tokens.text), (QPalette.ToolTipBase, tokens.base),
                        (QPalette.ToolTipText, tokens.text), (QPalette.PlaceholderText, tokens.muted),
                        (QPalette.Highlight, tokens.accent), (QPalette.HighlightedText, tokens.accent_text),
                        (QPalette.Accent, tokens.accent), (QPalette.Link, tokens.accent), (QPalette.Mid, tokens.line)):
        palette.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor(tokens.muted))
    app.setPalette(palette)
    app.setStyleSheet(style_sheet(tokens))


def style_sheet(t: Tokens) -> str:
    banners = "".join(
        f'QFrame[banner="{kind}"] {{ background: {back}; border-radius: 6px; }}'
        f'QFrame[banner="{kind}"] QLabel {{ color: {front}; background: transparent; }}'
        for kind, back, front in (("info", t.info_bg, t.info_fg), ("ok", t.ok_bg, t.ok_fg),
                                  ("warn", t.warn_bg, t.warn_fg), ("error", t.error_bg, t.error_fg)))
    mark = "dark" if t is DARK else "light"
    return f"""
    QCheckBox::indicator, QTreeView::indicator {{ width: 15px; height: 15px; border: 1px solid {t.muted}; border-radius: 3px;
                                                  background: {t.base}; }}
    QCheckBox::indicator:checked, QTreeView::indicator:checked {{ background: {t.accent}; border-color: {t.accent};
                                                                  image: url("{HERE}/check_{mark}.png"); }}
    QTreeView::indicator:indeterminate {{ background: {t.accent}; border-color: {t.accent};
                                          image: url("{HERE}/dash_{mark}.png"); }}
    QTreeView::indicator:disabled {{ border-color: {t.line}; background: {t.line}; }}
    QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid {t.muted}; border-radius: 8px; background: {t.base}; }}
    QRadioButton::indicator:checked {{ width: 6px; height: 6px; border: 5px solid {t.accent}; background: {t.accent_text}; }}
    QRadioButton::indicator:disabled {{ border-color: {t.line}; }}
    QLabel[role="title"] {{ font-size: 21px; font-weight: 600; }}
    QLabel[role="section"] {{ font-size: 14px; font-weight: 600; }}
    QLabel[role="muted"] {{ color: {t.muted}; }}
    QLabel[role="number"] {{ font-size: 20px; font-weight: 600; }}
    QFrame#rail {{ background: {t.rail}; border: none; }}
    QFrame#rail QLabel#brand {{ font-size: 16px; font-weight: 700; }}
    QPushButton[role="step"] {{ text-align: left; padding: 10px 12px; border: none; border-radius: 6px;
                                background: transparent; color: {t.text}; }}
    QPushButton[role="step"]:hover:enabled {{ background: {t.hover}; }}
    QPushButton[role="step"]:checked {{ background: {t.accent_soft}; font-weight: 600; }}
    QPushButton[role="step"]:disabled {{ color: {t.muted}; }}
    QPushButton[role="link"] {{ text-align: left; padding: 5px 12px; border: none; background: transparent; color: {t.muted}; }}
    QPushButton[role="link"]:hover {{ color: {t.accent}; background: transparent; }}
    QTabWidget::pane {{ border: 1px solid {t.line}; border-radius: 6px; background: {t.base}; }}
    QTabBar::tab {{ padding: 8px 14px; border: none; border-bottom: 2px solid transparent; background: transparent; color: {t.muted}; }}
    QTabBar::tab:selected {{ color: {t.text}; border-bottom-color: {t.accent}; font-weight: 600; }}
    QTextBrowser {{ border: none; background: {t.base}; }}
    QPushButton {{ padding: 7px 14px; border: 1px solid {t.line}; border-radius: 6px; background: {t.base}; color: {t.text}; }}
    QPushButton:hover:enabled {{ background: {t.hover}; }}
    QPushButton:focus {{ border-color: {t.accent}; }}
    QPushButton:disabled {{ color: {t.muted}; }}
    QPushButton[role="primary"] {{ background: {t.accent}; color: {t.accent_text}; border-color: {t.accent}; font-weight: 600; }}
    QPushButton[role="primary"]:hover:enabled {{ background: {t.accent_hover}; }}
    QPushButton[role="primary"]:disabled {{ background: {t.line}; color: {t.muted}; border-color: {t.line}; }}
    QPushButton[role="toggle"] {{ padding: 5px 12px; }}
    QPushButton[role="toggle"]:checked {{ background: {t.accent_soft}; border-color: {t.accent}; font-weight: 600; }}
    QLineEdit#field {{ padding: 6px 8px; border: 1px solid {t.line}; border-radius: 6px; background: {t.base}; color: {t.text}; }}
    QLineEdit#field:focus {{ border-color: {t.accent}; }}
    QComboBox, QAbstractSpinBox {{ min-height: 24px; }}
    QTreeView, QTableView, QListView {{ border: 1px solid {t.line}; border-radius: 6px; background: {t.base};
                                        selection-background-color: {t.accent_soft}; selection-color: {t.text}; }}
    QTreeView::item, QTreeView::item:selected {{ padding: 6px 4px; border: none; }}
    QTreeView::item:selected, QTableView::item:selected, QListView::item:selected {{ background: {t.accent_soft}; color: {t.text}; }}
    QHeaderView::section {{ background: {t.window}; color: {t.muted}; border: none; border-bottom: 1px solid {t.line};
                            padding: 6px 8px; }}
    QFrame[role="card"] {{ background: {t.base}; border: 1px solid {t.line}; border-radius: 6px; }}
    QProgressBar {{ border: none; border-radius: 5px; background: {t.line}; height: 10px; }}
    QProgressBar::chunk {{ border-radius: 5px; background: {t.accent}; }}
    QSplitter::handle {{ background: transparent; }}
    {banners}
    """
