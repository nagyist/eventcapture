import os
import sys
import datetime

from PyQt4 import uic
from PyQt4.QtCore import Qt, QSettings, QString, QEvent
from PyQt4.QtGui import QApplication, QWidget, QIcon, QFileDialog, QMessageBox

from eventcapture.eventRecorder import EventRecorder

def encode_from_qstring(qstr):
    """Convert the given QString into a Python str with the same encoding as the filesystem."""
    assert isinstance(qstr, QString)
    return unicode(qstr).encode( sys.getfilesystemencoding() )

class EventRecorderGui(QWidget):
    
    def __init__(self, parent=None, default_save_dir=None):
        super( EventRecorderGui, self ).__init__(parent)
        uiPath = os.path.join( os.path.split(__file__)[0], 'eventRecorderGui.ui' )
        self._default_save_dir = default_save_dir
        uic.loadUi(uiPath, self)

        self.setWindowTitle("Event Recorder")

        self.pauseButton.clicked.connect( self._onPause )
        self.saveButton.clicked.connect( self._onSave )
        self.insertCommentButton.clicked.connect( self._onInsertComment )
        
        self._recorder = EventRecorder( parent=self )
        
        self.pauseButton.setEnabled(False)
        self.saveButton.setEnabled(False)
        self.newCommentEdit.setEnabled(True)
        self.authorEdit.setEnabled(True)
        self.commentsDisplayEdit.setReadOnly(True)

        icons_dir = os.path.split(__file__)[0] + '/icons/'
        self.pauseButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.pauseButton.setIcon( QIcon(icons_dir + 'media-playback-pause.png') )
        self.pauseButton.setEnabled(True)
        self.saveButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.saveButton.setEnabled(True)
        self.saveButton.setIcon( QIcon(icons_dir + 'media-playback-stop.png') )

        self._autopaused = False
        self._saved = False
        
        QApplication.instance().focusChanged.connect(self._onFocusChanged)

        # Pre-populate the author name for convenience        
        settings = QSettings("eventcapture", "gui")
        variant = settings.value("author_name")
        if not variant.isNull():
            self.authorEdit.setText( variant.toString() )
    
    def openInPausedState(self):
        self.show()
        self.newCommentEdit.setFocus( Qt.MouseFocusReason )
        self._onPause(True)

    def confirmQuit(self):
        if self._recorder is not None and not self._saved:
            message = "You haven't saved your recording.  Are you sure you want to quit now?\n"
            buttons = QMessageBox.Discard | QMessageBox.Cancel
            response = QMessageBox.warning(self, "Discard recording?", message, buttons, defaultButton=QMessageBox.Cancel)
            if response == QMessageBox.Cancel:
                return False
        return True
    
    def _onPause(self, autopaused=False):
        self._autopaused = autopaused
        if self._recorder.paused:
            # Auto-add the comment (if any)
            if str(self.newCommentEdit.toPlainText()) != "":
                self._onInsertComment()
            # Unpause the recorder
            self._recorder.unpause()
            self.pauseButton.setText( "Pause" )
            self.pauseButton.setChecked( False )
            if not self._autopaused:
                self._saved = False
        else:
            # Pause the recorder
            self._recorder.pause()
            self.pauseButton.setText( "Unpause" )
            self.pauseButton.setChecked( True )

    def _onSave(self):
        # If we are actually playing a recording right now, then the "Stop Recording" action gets triggered as the last step.
        # Ignore it.
        if self._recorder is None:
            return

        self.commentsDisplayEdit.setFocus(True)
        self._autopaused = False

        if not self._recorder.paused:
            self._onPause(False)

        settings = QSettings("eventcapture", "gui")

        # Author name is required
        author_name = str( self.authorEdit.text() )
        if author_name == '':
            QMessageBox.critical(self, "Author name required", "Please enter your name as the author of this test case.")
            return
        else:
            # Save as default for next recording.
            settings.setValue( "author_name", author_name )

        default_dir = self._default_save_dir
        variant = settings.value("recordings_directory")
        if not variant.isNull():
            default_dir = str( variant.toString() )
        if default_dir is None:
            default_dir = ''

        now = datetime.datetime.now()
        timestr = "{:04d}{:02d}{:02d}-{:02d}{:02d}".format( now.year, now.month, now.day, now.hour, now.minute )
        default_script_path = os.path.join( default_dir, "recording-{timestr}.py".format( timestr=timestr ) )
            
        dlg = QFileDialog(self, "Save Playback Script", default_script_path, "eventcapture scripts (*.py)")
        dlg.setObjectName("event_recorder_save_dlg")
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        dlg.setOptions( QFileDialog.Options(QFileDialog.DontUseNativeDialog) )
        dlg.exec_()
        
        # If the user cancelled, stop now
        if dlg.result() == QFileDialog.Rejected:
            return
    
        script_path = encode_from_qstring( dlg.selectedFiles()[0] )
        
        # Remember the directory as our new default
        default_dir = os.path.split(script_path)[0]
        settings.setValue( "recordings_directory", default_dir )
        
        with open(script_path, 'w') as f:
            self._recorder.writeScript(f, author_name)
        self._saved = True
            
    def _onInsertComment(self):
        comment = self.newCommentEdit.toPlainText()
        if str(comment) == "":
            return
        self._recorder.insertComment( comment )
        self.commentsDisplayEdit.appendPlainText("--------------------------------------------------")
        self.commentsDisplayEdit.appendPlainText( comment )
        self.commentsDisplayEdit.appendPlainText("--------------------------------------------------")
        self.newCommentEdit.clear()

    def _is_descendent(self, widget):
        while widget is not None:
            if widget is self:
                return True
            widget = widget.parent()
        return False

    def _onFocusChanged(self, old, new):
        old_is_descendent = self._is_descendent(old)
        new_is_descendent = self._is_descendent(new)
        if new_is_descendent and not old_is_descendent:
            # This is a focus-in change
            if not self._recorder.paused:
                self._onPause(True)
        elif not new_is_descendent and old_is_descendent:
            # This is a focus-out change
            if self._autopaused and self._recorder.paused:
                self._onPause(False)

    def changeEvent(self, event):
        """
        Overridden from QWidget.
        Apparently the _onFocusChanged handler above doesn't work in all cases.
        In some cases, I can activate the main window but the keyboard focus remains 
        with the recorder gui, which means the recorder is not unpaused at the right time.
        By watching for change events, we ensure that the recorder is unpaused correctly.
        
        TODO: Perhaps we can just get rid of the focusChanged signal handler and just watch for changeEvents.
        """
        super( EventRecorderGui, self ).changeEvent(event)
        if event.type() == QEvent.ActivationChange and not self.isActiveWindow():
            if self._autopaused and self._recorder.paused:
                self._onPause(False)
