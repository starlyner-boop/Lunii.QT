"""
"Créer un livre audio" dialog : pick MP3 chapters + a cover, build a STUdio pack and import it.
"""
import os
from pathlib import Path
from typing import List, Optional

from PySide6 import QtCore
from PySide6.QtCore import Qt, QObject, QThread, Signal, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton,
                               QListWidget, QListWidgetItem, QFileDialog, QCheckBox, QProgressBar, QMessageBox,
                               QAbstractItemView, QGroupBox, QFrame)

from pkg.api.audiobook import (AUDIO_EXT, IMAGE_EXT, Chapter, build_audiobook_pack, find_cover, guess_book_title,
                               guess_chapter_name, natural_key, safe_filename, tts_available)
from pkg.api.constants import which_ffmpeg

DEFAULT_OUT_DIR = str(Path.home() / "Documents" / "Lunii - Livres audio")
ROLE_PATH = Qt.UserRole


class _BuildWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(str, str)   # zip path, error message

    def __init__(self, kwargs):
        super().__init__()
        self.kwargs = kwargs
        self.aborted = False

    def run(self):
        try:
            path = build_audiobook_pack(progress=lambda a, b, m: self.progress.emit(a, b, m),
                                        abort=lambda: self.aborted, **self.kwargs)
            self.finished.emit(path, "")
        except Exception as e:
            self.finished.emit("", str(e))


class ChapterList(QListWidget):
    """Reorderable list that also accepts audio files dropped from the explorer."""
    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setAcceptDrops(True)
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.setAlternatingRowColors(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.files_dropped.emit([u.toLocalFile() for u in event.mimeData().urls()])
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class AudiobookDialog(QDialog):
    def __init__(self, parent=None, can_import=False, files: Optional[List[str]] = None):
        super().__init__(parent)
        self.setWindowTitle("Créer un livre audio")
        self.setMinimumSize(720, 560)
        self.can_import = can_import
        self.cover: Optional[bytes] = None
        self.cover_auto = True
        self.result_zip: Optional[str] = None
        self.thread: Optional[QThread] = None
        self.worker: Optional[_BuildWorker] = None
        self.import_after = False

        self._build_ui()
        self._update_buttons()
        if files:
            self.add_paths(files)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QVBoxLayout(self)

        # title + cover
        top = QHBoxLayout()
        info = QGridLayout()
        info.addWidget(QLabel("Titre du livre :"), 0, 0)
        self.le_title = QLineEdit()
        self.le_title.setPlaceholderText("ex : Le Petit Prince")
        self.le_title.textChanged.connect(self._update_buttons)
        info.addWidget(self.le_title, 0, 1)
        info.addWidget(QLabel("Description :"), 1, 0)
        self.le_desc = QLineEdit()
        self.le_desc.setPlaceholderText("(facultatif)")
        info.addWidget(self.le_desc, 1, 1)
        info.setRowStretch(2, 1)
        top.addLayout(info, 1)

        cover_box = QVBoxLayout()
        self.lbl_cover = QLabel("Aucune\ncouverture")
        self.lbl_cover.setFixedSize(160, 120)
        self.lbl_cover.setAlignment(Qt.AlignCenter)
        self.lbl_cover.setFrameShape(QFrame.Box)
        self.lbl_cover.setToolTip("Cliquez pour choisir l'image de couverture")
        self.lbl_cover.mousePressEvent = lambda e: self.choose_cover()
        cover_box.addWidget(self.lbl_cover)
        row = QHBoxLayout()
        btn = QPushButton("Couverture…")
        btn.clicked.connect(self.choose_cover)
        row.addWidget(btn)
        self.btn_cover_rm = QPushButton("✕")
        self.btn_cover_rm.setFixedWidth(28)
        self.btn_cover_rm.setToolTip("Retirer la couverture")
        self.btn_cover_rm.clicked.connect(lambda: self.set_cover(None, auto=False))
        row.addWidget(self.btn_cover_rm)
        cover_box.addLayout(row)
        top.addLayout(cover_box)
        root.addLayout(top)

        # chapters
        group = QGroupBox("Chapitres, dans l'ordre de lecture")
        gl = QHBoxLayout(group)
        self.list = ChapterList()
        self.list.setToolTip("Double-clic : renommer (c'est ce nom qui sera annoncé)\n"
                             "Glisser : réordonner\nVous pouvez aussi déposer ici des MP3, un dossier ou une image")
        self.list.files_dropped.connect(self.add_paths)
        self.list.model().rowsInserted.connect(self._update_buttons)
        self.list.model().rowsRemoved.connect(self._update_buttons)
        self.list.itemSelectionChanged.connect(self._update_buttons)
        gl.addWidget(self.list, 1)

        side = QVBoxLayout()
        for text, slot in [("Ajouter des MP3…", self.add_files),
                           ("Ajouter un dossier…", self.add_folder)]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            side.addWidget(b)
        side.addSpacing(10)
        self.btn_up = QPushButton("▲ Monter")
        self.btn_up.clicked.connect(lambda: self.move_selected(-1))
        self.btn_down = QPushButton("▼ Descendre")
        self.btn_down.clicked.connect(lambda: self.move_selected(1))
        self.btn_sort = QPushButton("Trier par nom de fichier")
        self.btn_sort.clicked.connect(self.sort_by_filename)
        self.btn_rm = QPushButton("Retirer")
        self.btn_rm.clicked.connect(self.remove_selected)
        self.btn_clear = QPushButton("Tout vider")
        self.btn_clear.clicked.connect(self.list.clear)
        for b in (self.btn_up, self.btn_down, self.btn_sort, self.btn_rm, self.btn_clear):
            side.addWidget(b)
        side.addStretch(1)
        gl.addLayout(side)
        root.addWidget(group, 1)

        # options
        opts = QGroupBox("Options")
        ol = QGridLayout(opts)
        self.cb_tts = QCheckBox("Annoncer le titre et le nom des chapitres avec une voix de synthèse")
        self.cb_tts.setChecked(tts_available())
        self.cb_tts.setEnabled(tts_available())
        if not tts_available():
            self.cb_tts.setToolTip("Disponible uniquement sous Windows")
        ol.addWidget(self.cb_tts, 0, 0, 1, 3)
        self.cb_nm = QCheckBox("Activer le mode nuit")
        ol.addWidget(self.cb_nm, 1, 0, 1, 3)
        ol.addWidget(QLabel("Dossier des packs :"), 2, 0)
        self.le_out = QLineEdit(DEFAULT_OUT_DIR)
        ol.addWidget(self.le_out, 2, 1)
        b = QPushButton("…")
        b.setFixedWidth(28)
        b.clicked.connect(self.choose_out_dir)
        ol.addWidget(b, 2, 2)
        root.addWidget(opts)

        # progress + actions
        self.lbl_status = QLabel("")
        self.pbar = QProgressBar()
        self.pbar.setVisible(False)
        root.addWidget(self.lbl_status)
        root.addWidget(self.pbar)

        bottom = QHBoxLayout()
        if not which_ffmpeg():
            warn = QLabel("⚠ FFMPEG introuvable (menu Outils pour l'installer)")
            warn.setStyleSheet("color: #c0392b")
            bottom.addWidget(warn)
        bottom.addStretch(1)
        self.btn_pack = QPushButton("Créer le pack seulement")
        self.btn_pack.clicked.connect(lambda: self.start_build(import_after=False))
        self.btn_import = QPushButton("Créer et importer")
        self.btn_import.setDefault(True)
        self.btn_import.clicked.connect(lambda: self.start_build(import_after=True))
        if not self.can_import:
            self.btn_import.setToolTip("Branchez et sélectionnez votre Lunii/Flam pour importer directement")
        self.btn_close = QPushButton("Fermer")
        self.btn_close.clicked.connect(self.reject)
        for b in (self.btn_pack, self.btn_import, self.btn_close):
            bottom.addWidget(b)
        root.addLayout(bottom)

    def _update_buttons(self, *args):
        busy = self.thread is not None
        has_sel = bool(self.list.selectedItems())
        for b in (self.btn_up, self.btn_down, self.btn_rm):
            b.setEnabled(has_sel and not busy)
        ready = self.list.count() > 0 and bool(self.le_title.text().strip()) and bool(which_ffmpeg()) and not busy
        self.btn_pack.setEnabled(ready)
        self.btn_import.setEnabled(ready and self.can_import)
        self.btn_cover_rm.setEnabled(self.cover is not None and not busy)
        self.btn_close.setText("Annuler" if busy else "Fermer")

    # ------------------------------------------------------------------ chapters
    def add_paths(self, paths: List[str]):
        files, images = [], []
        for p in paths:
            p = Path(p)
            if p.is_dir():
                for f in p.iterdir():
                    if f.suffix.lower() in AUDIO_EXT:
                        files.append(str(f))
            elif p.suffix.lower() in AUDIO_EXT:
                files.append(str(p))
            elif p.suffix.lower() in IMAGE_EXT:
                images.append(str(p))

        if images:
            self.set_cover(Path(images[0]).read_bytes(), auto=False)
        if not files:
            return

        files.sort(key=lambda f: natural_key(Path(f).name))
        was_empty = self.list.count() == 0
        for f in files:
            index = self.list.count() + 1
            item = QListWidgetItem(guess_chapter_name(f, index))
            item.setData(ROLE_PATH, f)
            item.setToolTip(f)
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            self.list.addItem(item)

        if was_empty and not self.le_title.text().strip():
            self.le_title.setText(guess_book_title(files))
        if self.cover is None and self.cover_auto:
            found = find_cover(files)
            if found:
                self.set_cover(found, auto=True)
        self._update_buttons()

    def add_files(self):
        exts = " ".join(f"*{e}" for e in AUDIO_EXT)
        files, _ = QFileDialog.getOpenFileNames(self, "Choisir les chapitres", "", f"Fichiers audio ({exts});;Tous (*)")
        if files:
            self.add_paths(files)

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choisir le dossier du livre audio")
        if folder:
            self.add_paths([folder])

    def move_selected(self, offset):
        rows = sorted(self.list.row(i) for i in self.list.selectedItems())
        if not rows:
            return
        if (offset < 0 and rows[0] == 0) or (offset > 0 and rows[-1] == self.list.count() - 1):
            return
        for row in (rows if offset < 0 else reversed(rows)):
            item = self.list.takeItem(row)
            self.list.insertItem(row + offset, item)
        self.list.clearSelection()
        for row in rows:
            self.list.item(row + offset).setSelected(True)

    def sort_by_filename(self):
        items = [self.list.takeItem(0) for _ in range(self.list.count())]
        items.sort(key=lambda it: natural_key(Path(it.data(ROLE_PATH)).name))
        for it in items:
            self.list.addItem(it)

    def remove_selected(self):
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))

    # ------------------------------------------------------------------ cover / output
    def choose_cover(self):
        if self.thread:
            return
        exts = " ".join(f"*{e}" for e in IMAGE_EXT)
        file, _ = QFileDialog.getOpenFileName(self, "Choisir la couverture", "", f"Images ({exts})")
        if file:
            self.set_cover(Path(file).read_bytes(), auto=False)

    def set_cover(self, data: Optional[bytes], auto: bool):
        self.cover_auto = auto
        pix = QPixmap()
        if data and pix.loadFromData(data):
            self.cover = data
            self.lbl_cover.setPixmap(pix.scaled(self.lbl_cover.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.cover = None
            self.lbl_cover.setPixmap(QPixmap())
            self.lbl_cover.setText("Aucune\ncouverture")
        self._update_buttons()

    def choose_out_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Dossier des packs", self.le_out.text())
        if folder:
            self.le_out.setText(folder)

    # ------------------------------------------------------------------ build
    def chapters(self) -> List[Chapter]:
        result = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            result.append(Chapter(it.data(ROLE_PATH), it.text().strip() or f"Chapitre {i + 1}"))
        return result

    def start_build(self, import_after: bool):
        title = self.le_title.text().strip()
        out_dir = self.le_out.text().strip() or DEFAULT_OUT_DIR
        out_zip = os.path.join(out_dir, f"{safe_filename(title)}.zip")
        if os.path.exists(out_zip):
            if QMessageBox.question(self, "Pack existant",
                                    f"« {Path(out_zip).name} » existe déjà dans ce dossier.\nLe remplacer ?") != QMessageBox.Yes:
                return

        self.import_after = import_after
        self.worker = _BuildWorker(dict(title=title, chapters=self.chapters(), out_zip=out_zip, cover=self.cover,
                                        description=self.le_desc.text().strip(), announce=self.cb_tts.isChecked(),
                                        night_mode=self.cb_nm.isChecked()))
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)

        self.pbar.setVisible(True)
        self.pbar.setValue(0)
        self.list.setEnabled(False)
        self.thread.start()
        self._update_buttons()

    def on_progress(self, step, total, msg):
        self.pbar.setMaximum(total)
        self.pbar.setValue(step)
        self.lbl_status.setText(msg)

    def on_finished(self, path, error):
        self.thread.quit()
        self.thread.wait()
        self.worker.deleteLater()
        self.thread.deleteLater()
        self.thread = None
        self.worker = None
        self.pbar.setVisible(False)
        self.list.setEnabled(True)
        self._update_buttons()

        if error:
            self.lbl_status.setText("")
            if error != "Création annulée":
                QMessageBox.critical(self, "Erreur", f"La création du pack a échoué :\n\n{error}")
            return

        self.result_zip = path
        if self.import_after:
            self.accept()
            return

        self.lbl_status.setText(f"✅ Pack créé : {path}")
        box = QMessageBox(self)
        box.setWindowTitle("Pack créé")
        box.setText(f"Le pack a été créé :\n{path}\n\nVous pourrez l'importer plus tard via Histoires > Importer, "
                    f"ou en le glissant sur la liste des histoires.")
        open_btn = box.addButton("Ouvrir le dossier", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() == open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def reject(self):
        if self.worker:
            self.worker.aborted = True
            self.lbl_status.setText("Annulation…")
            return
        super().reject()
