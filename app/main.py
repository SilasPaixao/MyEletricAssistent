"""PySide6 desktop client."""
import sys
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog, QMessageBox, QTableWidget,
    QTableWidgetItem, QComboBox, QDialog, QFormLayout, QDialogButtonBox,
    QHeaderView, QAbstractItemView, QCheckBox, QInputDialog)
from .core import API, MyEAError, load_entries, validate_photo, planned_to_used, save_report
from . import updater

class Worker(QThread):
    progress = Signal(int, str, str)
    def __init__(self, api, tasks):
        super().__init__(); self.api = api; self.tasks = tasks
    def run(self):
        for idx, entry, vehicle in self.tasks:
            try:
                self.api.finish(entry, vehicle)
                self.progress.emit(idx, 'Pendente de aprovação', '')
            except Exception as exc:
                self.progress.emit(idx, 'Erro', str(exc))

class UpdateWorker(QThread):
    checked = Signal(object)
    downloaded = Signal(object)
    failed = Signal(str)
    percent = Signal(int)

    def __init__(self, update=None):
        super().__init__()
        self.update = update

    def run(self):
        try:
            if self.update is None:
                self.checked.emit(updater.check_latest())
            else:
                self.downloaded.emit(updater.download_verified(self.update, self.percent.emit))
        except Exception as exc:
            self.failed.emit(str(exc))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('MyEletricAssistent — Coordenação de Elétrica')
        self.resize(1150, 720)
        self.api = None; self.entries = []; self.teams = {}; self.users = []; self.vehicles = []
        self.worker = None; self.update_worker = None; self.download_worker = None; self.pending_update_path = None
        root = QWidget(); self.setCentralWidget(root); layout = QVBoxLayout(root)
        auth = QHBoxLayout(); layout.addLayout(auth)
        self.url = QLineEdit('https://SEU-DOMINIO'); self.url.setPlaceholderText('URL do servidor HTTPS')
        self.username = QLineEdit(); self.username.setPlaceholderText('Usuário')
        self.password = QLineEdit(); self.password.setEchoMode(QLineEdit.EchoMode.Password); self.password.setPlaceholderText('Senha')
        self.login_btn = QPushButton('Entrar'); self.login_btn.clicked.connect(self.login)
        for widget in (self.url, self.username, self.password, self.login_btn): auth.addWidget(widget)
        actions = QHBoxLayout(); layout.addLayout(actions)
        self.import_btn = QPushButton('Abrir JSON e fotos'); self.import_btn.clicked.connect(self.import_json)
        self.team_btn = QPushButton('Adicionar equipe'); self.team_btn.clicked.connect(self.configure_teams)
        self.clear_teams_btn = QPushButton('Limpar equipes'); self.clear_teams_btn.clicked.connect(self.clear_teams)
        self.select_btn = QPushButton('Selecionar todas'); self.select_btn.clicked.connect(lambda: self.select_all(True))
        self.unselect_btn = QPushButton('Desmarcar todas'); self.unselect_btn.clicked.connect(lambda: self.select_all(False))
        self.check_btn = QPushButton('Validar selecionadas'); self.check_btn.clicked.connect(self.validate)
        self.run_btn = QPushButton('Dar baixa nas selecionadas'); self.run_btn.clicked.connect(self.execute)
        self.report_btn = QPushButton('Exportar relatório'); self.report_btn.clicked.connect(self.report)
        for widget in (self.import_btn, self.team_btn, self.clear_teams_btn, self.select_btn, self.unselect_btn, self.check_btn, self.run_btn, self.report_btn): actions.addWidget(widget)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(['Selecionar', 'Referência', 'Descrição', 'Eletricistas', 'Fotos', 'Equipe', 'Status', 'Detalhes'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.cellDoubleClicked.connect(self.show_detail)
        layout.addWidget(self.table)
        self.status = QLabel('Faça login para começar.'); layout.addWidget(self.status)
        self.update_btn = QPushButton(f'Verificar atualizações (v{updater.APP_VERSION})')
        self.update_btn.setEnabled(updater.is_configured())
        self.update_btn.clicked.connect(self.check_updates)
        layout.addWidget(self.update_btn)
        self.set_enabled(False)

    def check_updates(self):
        if self.update_worker and self.update_worker.isRunning():
            return
        self.update_btn.setEnabled(False)
        self.status.setText('Verificando atualizações...')
        self.update_worker = UpdateWorker()
        self.update_worker.checked.connect(self.on_update_checked)
        self.update_worker.failed.connect(self.on_update_failed)
        self.update_worker.finished.connect(lambda: self.update_btn.setEnabled(updater.is_configured()))
        self.update_worker.start()

    def on_update_checked(self, update):
        if not update:
            self.status.setText('Você já está na versão mais recente.')
            QMessageBox.information(self, 'Atualizações', 'O aplicativo está atualizado.')
            return
        answer = QMessageBox.question(self, 'Atualização disponível',
            f"Versão {update['version']} disponível (instalada: {updater.APP_VERSION}).\n"
            'Deseja baixar, verificar e instalar agora? O aplicativo será reiniciado.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not getattr(sys, 'frozen', False) or sys.platform != 'win32':
            self.alert('Instalação automática disponível somente no .exe Windows.')
            return
        if self.worker and self.worker.isRunning():
            self.alert('Aguarde as baixas em andamento antes de atualizar.')
            return
        self.update_btn.setEnabled(False)
        self.download_worker = UpdateWorker(update)
        self.download_worker.percent.connect(lambda n: self.status.setText(f'Baixando atualização: {n}%'))
        self.download_worker.downloaded.connect(self.on_update_downloaded)
        self.download_worker.failed.connect(self.on_update_failed)
        self.download_worker.finished.connect(self.finish_update_download)
        self.download_worker.start()

    def on_update_downloaded(self, path):
        self.pending_update_path = path

    def finish_update_download(self):
        self.update_btn.setEnabled(updater.is_configured())
        if not self.pending_update_path:
            return
        path = self.pending_update_path
        self.pending_update_path = None
        if self.worker and self.worker.isRunning():
            self.alert('Há baixas em andamento; atualização cancelada.')
            return
        try:
            updater.launch_replacement(path)
        except Exception as exc:
            self.alert(f'Não foi possível iniciar o atualizador: {exc}')
            return
        QApplication.instance().quit()

    def on_update_failed(self, message):
        self.status.setText('Não foi possível verificar/baixar atualização.')
        self.alert(f'Falha na atualização: {message}')

    def set_enabled(self, enabled):
        for w in (self.import_btn, self.team_btn, self.clear_teams_btn, self.select_btn, self.unselect_btn, self.check_btn, self.run_btn, self.report_btn): w.setEnabled(enabled)

    def alert(self, text): QMessageBox.warning(self, 'MyEletricAssistent', text)

    def login(self):
        try:
            url = self.url.text().strip()
            if not url.startswith('https://') and not url.startswith('http://localhost') and not url.startswith('http://127.0.0.1'):
                raise MyEAError('Utilize HTTPS para acessar o servidor remoto')
            if self.api: self.api.close()
            self.api = API(url); self.api.login(self.username.text().strip(), self.password.text())
            self.users = self.api.electricians(); self.vehicles = self.api.vehicles()
            self.password.clear(); self.set_enabled(True)
            self.status.setText(f"Autenticado: {self.api.user.get('name')} · {len(self.users)} eletricistas · {len(self.vehicles)} veículos")
        except Exception as exc: self.alert(str(exc))

    def import_json(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Escolha o JSON', '', 'JSON (*.json)')
        if not path: return
        folder = QFileDialog.getExistingDirectory(self, 'Escolha a pasta que contém as mídias', str(Path(path).parent))
        if not folder: return
        try:
            self.entries = load_entries(Path(path), Path(folder))
            for entry in self.entries:
                try:
                    entry.remote = self.api.demand(entry.reference)
                    if entry.remote.get('status') != 'PENDING': entry.error = f"Status: {entry.remote.get('status')}"
                    validate_photo(entry)
                    planned_to_used(entry.remote)
                except Exception as exc: entry.error = str(exc)
            self.refresh()
        except Exception as exc: self.alert(str(exc))

    def refresh(self):
        self.table.setRowCount(len(self.entries))
        for i, e in enumerate(self.entries):
            check = QCheckBox(); check.setChecked(e.selected)
            check.stateChanged.connect(lambda state, ix=i: setattr(self.entries[ix], 'selected', bool(state)))
            self.table.setCellWidget(i, 0, check)
            electricians = ', '.join(u.get('name','') for u in e.remote.get('electricians', []))
            description = e.remote.get('description', '')[:90]
            for col, value in ((1,e.reference),(2,description),(3,electricians),(4,str(len(e.photos))),(6,e.result),(7,e.error)):
                self.table.setItem(i, col, QTableWidgetItem(str(value)))
            combo = QComboBox(); combo.addItem('Selecione equipe', '')
            for name in self.teams: combo.addItem(name, name)
            if e.team:
                idx = combo.findData(e.team)
                if idx >= 0: combo.setCurrentIndex(idx)
            combo.currentIndexChanged.connect(lambda _n, ix=i, w=combo: setattr(self.entries[ix], 'team', w.currentData() or ''))
            self.table.setCellWidget(i, 5, combo)
        self.status.setText(f'{len(self.entries)} demandas carregadas')

    def select_all(self, selected):
        for e in self.entries: e.selected = selected
        self.refresh()

    def clear_teams(self):
        if QMessageBox.question(self, 'Limpar equipes', 'Remover todas as equipes configuradas?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.teams.clear()
            for entry in self.entries: entry.team = ''
            self.refresh()

    def show_detail(self, row, column):
        if row >= len(self.entries): return
        e = self.entries[row]
        try:
            materials = planned_to_used(e.remote)
            lines = [f"Referência: {e.reference}", f"Local: {e.remote.get('location', '')}",
                     f"Descrição: {e.remote.get('description', '')}", 'Materiais planejados → utilizados:']
            names = {m.get('materialId'): m.get('material', {}).get('name', m.get('materialId')) for m in e.remote.get('plannedMaterials', [])}
            lines.extend(f"• {names.get(m['materialId'])}: {m['quantity']}" for m in materials)
            lines.append('Fotografias:')
            lines.extend(f"• {p.name}" for p in e.photos)
            QMessageBox.information(self, 'Conferência da demanda', '\n'.join(lines))
        except Exception as exc: self.alert(str(exc))

    def configure_teams(self):
        if not self.users or not self.vehicles: self.alert('Cadastre eletricistas e veículos no sistema antes de configurar equipes'); return
        dialog = QDialog(self); dialog.setWindowTitle('Adicionar equipe'); form = QFormLayout(dialog)
        a = QComboBox(); b = QComboBox(); v = QComboBox()
        for u in self.users: a.addItem(u['name'], u['id'])
        b.addItem('Ninguém (sozinho)', '')
        for u in self.users: b.addItem(u['name'], u['id'])
        for vehicle in self.vehicles: v.addItem(vehicle['name'], vehicle['id'])
        form.addRow('Eletricista 1', a); form.addRow('Eletricista 2', b); form.addRow('Veículo', v)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        if a.currentData() == b.currentData(): self.alert('Não repita o mesmo eletricista'); return
        for name, team in self.teams.items():
            if a.currentData() in team['members'] or (b.currentData() and b.currentData() in team['members']):
                self.alert(f'Eletricista já vinculado à equipe {name}. Remova a equipe antes de reutilizar.'); return
        name = a.currentText() + (' + ' + b.currentText() if b.currentData() else ' (sozinho)')
        self.teams[name] = {'members': [x for x in (a.currentData(), b.currentData()) if x], 'vehicle_id': v.currentData(), 'vehicle_name': v.currentText()}
        self.refresh()
        self.status.setText(f'Equipe criada: {name} → {v.currentText()}. Para alterar, limpe e configure as equipes novamente.')

    def _check_entry(self, e):
        if not e.team or e.team not in self.teams: raise MyEAError('Equipe não configurada')
        validate_photo(e)
        demand = self.api.demand(e.reference)
        if demand.get('status') != 'PENDING': raise MyEAError(f"Status não permite baixa: {demand.get('status')}")
        planned_to_used(demand)
        team = self.teams[e.team]
        actual = {u['id'] for u in demand.get('electricians', [])}
        if actual and actual != set(team['members']):
            raise MyEAError('Equipe selecionada difere dos eletricistas cadastrados na demanda; corrija a vinculação no sistema')
        if not any(v['id'] == team['vehicle_id'] for v in self.api.vehicles()): raise MyEAError('Veículo removido do cadastro')
        return team['vehicle_id']

    def validate(self):
        for e in self.entries:
            if not e.selected: continue
            try: self._check_entry(e); e.error = ''; e.result = 'Apta'
            except Exception as exc: e.error = str(exc); e.result = 'Bloqueada'
        self.refresh()

    def execute(self):
        if self.worker and self.worker.isRunning(): return
        self.validate()
        tasks = []
        for i,e in enumerate(self.entries):
            if e.selected and e.result == 'Apta': tasks.append((i,e,self.teams[e.team]['vehicle_id']))
        if not tasks: self.alert('Nenhuma demanda apta selecionada'); return
        reply = QMessageBox.question(self, 'Confirmar baixas', f'Enviar {len(tasks)} demandas para PENDING_APPROVAL? A operação altera dados reais no servidor.', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes: return
        self.run_btn.setEnabled(False)
        self.worker = Worker(self.api, tasks)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(lambda: self.run_btn.setEnabled(True))
        self.worker.start()

    def on_progress(self, index, result, error):
        e = self.entries[index]; e.result = result; e.error = error
        self.table.item(index, 6).setText(result); self.table.item(index, 7).setText(error)
        self.status.setText(f'{e.reference}: {result}')

    def report(self):
        if not self.entries: return
        path, _ = QFileDialog.getSaveFileName(self, 'Salvar relatório', 'relatorio_myea.csv', 'CSV (*.csv)')
        if path:
            try: save_report(self.entries, Path(path)); self.status.setText('Relatório salvo')
            except Exception as exc: self.alert(str(exc))

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.alert('Aguarde a conclusão das baixas antes de fechar'); event.ignore(); return
        if ((self.update_worker and self.update_worker.isRunning()) or
                (self.download_worker and self.download_worker.isRunning())):
            self.alert('Aguarde a verificação/download da atualização'); event.ignore(); return
        if self.api: self.api.close()
        event.accept()

def main():
    app = QApplication(sys.argv)
    window = MainWindow(); window.show()
    sys.exit(app.exec())

if __name__ == '__main__': main()
