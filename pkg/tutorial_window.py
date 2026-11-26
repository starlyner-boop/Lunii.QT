"""
Startup tutorial for the "Créer un livre audio" feature.
Shown at launch until "Ne plus afficher au démarrage" is ticked, can be reopened from the Help menu.
"""
import json
import os

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QPainter, QColor, QFont, QPen
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox, QStackedWidget,
                               QWidget, QSizePolicy)

from pkg.api.constants import CFG_DIR

SETTINGS_FILE = os.path.join(CFG_DIR, "audiobook.json")


# ---------------------------------------------------------------------- settings
def _load():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:
        return {}


def tutorial_enabled() -> bool:
    return _load().get("show_tutorial", True)


def set_tutorial_enabled(value: bool):
    data = _load()
    data["show_tutorial"] = value
    try:
        os.makedirs(CFG_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------------- illustrations
class FlowDiagram(QWidget):
    """Small drawing of what the child sees on the device: cover -> chapter menu -> playback."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        fg = pal.windowText().color()
        accent = QColor(41, 128, 185)

        screens = [("📖", "Couverture", "titre annoncé"),
                   ("1 / 9", "Menu", "molette = chapitre"),
                   ("▶", "Lecture", "enchaîne la suite")]
        w, h, gap = 120, 90, 50
        total = len(screens) * w + (len(screens) - 1) * gap
        x0 = (self.width() - total) / 2
        y0 = 10

        for i, (icon, title, sub) in enumerate(screens):
            x = x0 + i * (w + gap)
            rect = QRectF(x, y0, w, h)
            p.setPen(QPen(accent, 2))
            p.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 30))
            p.drawRoundedRect(rect, 10, 10)
            f = QFont(self.font())
            f.setPointSize(20)
            f.setBold(True)
            p.setFont(f)
            p.setPen(fg)
            p.drawText(rect, Qt.AlignCenter, icon)
            f.setPointSize(10)
            p.setFont(f)
            p.drawText(QRectF(x - 15, y0 + h + 6, w + 30, 18), Qt.AlignCenter, title)
            f.setBold(False)
            f.setPointSize(8)
            p.setFont(f)
            p.drawText(QRectF(x - 20, y0 + h + 24, w + 40, 16), Qt.AlignCenter, sub)

            if i < len(screens) - 1:
                ax = x + w + 8
                ay = y0 + h / 2
                p.setPen(QPen(fg, 2))
                p.drawLine(int(ax), int(ay), int(ax + gap - 16), int(ay))
                p.drawLine(int(ax + gap - 16), int(ay), int(ax + gap - 24), int(ay - 5))
                p.drawLine(int(ax + gap - 16), int(ay), int(ax + gap - 24), int(ay + 5))
                f.setPointSize(8)
                f.setBold(True)
                p.setFont(f)
                p.drawText(QRectF(ax, ay - 20, gap - 16, 14), Qt.AlignCenter, "OK")
        p.end()


# ---------------------------------------------------------------------- pages
PAGES = [
    ("🎧", "Nouveau : vos livres audio sur la Lunii / Flam",
     "Lunii.QT peut maintenant transformer un <b>livre audio</b> (un fichier MP3 par chapitre) "
     "en histoire pour votre conteuse, avec une couverture, un menu des chapitres et des annonces vocales."
     "<br><br>Pour commencer :"
     "<ul><li>menu <b>Histoires → Créer un livre audio…</b> (raccourci <b>Ctrl+B</b>)</li>"
     "<li>ou <b>glissez vos MP3</b> (ou leur dossier) directement sur la liste des histoires.</li></ul>",
     None),
    ("📂", "1. Choisir les chapitres",
     "<ul><li><b>Ajouter des MP3…</b> ou <b>Ajouter un dossier…</b> : les fichiers sont triés dans l'ordre de leur nom.</li>"
     "<li><b>Glissez</b> les chapitres pour changer l'ordre, ou utilisez ▲ / ▼.</li>"
     "<li><b>Double-cliquez</b> sur un chapitre pour le renommer : c'est ce nom qui sera <b>annoncé</b> et affiché.</li>"
     "<li>Le <b>titre</b> et la <b>couverture</b> sont trouvés automatiquement (infos des MP3, image du dossier). "
     "Cliquez sur la couverture pour en choisir une autre.</li></ul>",
     None),
    ("⚙️", "2. Les options",
     "<ul><li><b>Voix de synthèse</b> : le titre du livre et le nom de chaque chapitre sont lus à voix haute "
     "dans le menu (voix française de Windows).</li>"
     "<li><b>Mode nuit</b> : rend le livre disponible dans le mode nuit de la conteuse.</li>"
     "<li><b>Dossier des packs</b> : une copie de chaque livre y est gardée, pour pouvoir le réimporter plus tard.</li></ul>"
     "<i>FFMPEG est nécessaire pour convertir l'audio. S'il manque, installez-le depuis le menu <b>Outils</b>.</i>",
     None),
    ("📥", "3. Importer sur la conteuse",
     "<ul><li>Branchez votre Lunii / Flam et sélectionnez-la en haut de la fenêtre.</li>"
     "<li><b>Créer et importer</b> : le livre est préparé puis envoyé directement.</li>"
     "<li><b>Créer le pack seulement</b> : pour l'importer plus tard (Histoires → Importer, ou glisser le .zip).</li></ul>"
     "⏳ La Flam est lente en USB (environ 1 minute pour 35 Mo) : soyez patient.<br>"
     "⚠️ La Flam doit être en <b>firmware 2.x</b>. Pensez à <b>éjecter</b> la conteuse avant de la débrancher.",
     None),
    ("🧒", "4. Sur la conteuse",
     "<ul><li>Choisissez le livre comme une histoire : sa couverture s'affiche et le titre est annoncé.</li>"
     "<li><b>OK</b> ouvre le menu : tournez la <b>molette</b> pour choisir un chapitre, puis <b>OK</b>.</li>"
     "<li>À la fin d'un chapitre, <b>le suivant démarre tout seul</b>.</li>"
     "<li>Le bouton <b>Maison</b> revient au menu, <b>sur le chapitre en cours</b> : pratique pour reprendre plus tard.</li></ul>",
     FlowDiagram),
]


class _Page(QWidget):
    def __init__(self, icon, title, html, extra_cls):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 8)

        head = QHBoxLayout()
        lbl_icon = QLabel(icon)
        f = lbl_icon.font()
        f.setPointSize(30)
        lbl_icon.setFont(f)
        head.addWidget(lbl_icon)
        lbl_title = QLabel(title)
        f = lbl_title.font()
        f.setPointSize(14)
        f.setBold(True)
        lbl_title.setFont(f)
        lbl_title.setWordWrap(True)
        head.addWidget(lbl_title, 1)
        lay.addLayout(head)

        body = QLabel(html)
        body.setWordWrap(True)
        body.setTextFormat(Qt.RichText)
        body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lay.addWidget(body)
        if extra_cls:
            lay.addWidget(extra_cls())
        lay.addStretch(1)


class TutorialDialog(QDialog):
    create_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Livres audio - tutoriel")
        self.setFixedSize(600, 470)

        root = QVBoxLayout(self)
        self.stack = QStackedWidget()
        for page in PAGES:
            self.stack.addWidget(_Page(*page))
        root.addWidget(self.stack, 1)

        self.lbl_dots = QLabel()
        self.lbl_dots.setAlignment(Qt.AlignCenter)
        root.addWidget(self.lbl_dots)

        bottom = QHBoxLayout()
        self.cb_hide = QCheckBox("Ne plus afficher au démarrage")
        self.cb_hide.setChecked(not tutorial_enabled())
        self.cb_hide.toggled.connect(lambda checked: set_tutorial_enabled(not checked))
        bottom.addWidget(self.cb_hide)
        bottom.addStretch(1)
        self.btn_prev = QPushButton("◀ Précédent")
        self.btn_prev.clicked.connect(lambda: self.go(-1))
        self.btn_next = QPushButton("Suivant ▶")
        self.btn_next.setDefault(True)
        self.btn_next.clicked.connect(lambda: self.go(1))
        self.btn_create = QPushButton("Créer un livre audio")
        self.btn_create.clicked.connect(self._create)
        self.btn_close = QPushButton("Fermer")
        self.btn_close.clicked.connect(self.accept)
        for b in (self.btn_prev, self.btn_next, self.btn_create, self.btn_close):
            bottom.addWidget(b)
        root.addLayout(bottom)

        self._refresh()

    def go(self, offset):
        self.stack.setCurrentIndex(max(0, min(self.stack.count() - 1, self.stack.currentIndex() + offset)))
        self._refresh()

    def _refresh(self):
        idx, count = self.stack.currentIndex(), self.stack.count()
        self.lbl_dots.setText("  ".join("●" if i == idx else "○" for i in range(count)))
        self.btn_prev.setEnabled(idx > 0)
        last = idx == count - 1
        self.btn_next.setVisible(not last)
        self.btn_create.setVisible(last)
        (self.btn_create if last else self.btn_next).setDefault(True)

    def _create(self):
        self.accept()
        self.create_requested.emit()
