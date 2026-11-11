# MyEletricAssistent

Aplicativo desktop Python para dar baixa em demandas elétricas cadastradas no backend da Prefeitura, **sem aprovar** as demandas.

## Requisitos
- Windows 10/11 ou Linux com interface gráfica
- Python 3.12+
- API atualizada com `GET /api/demands/by-reference/:idReferencia` e suporte ao cabeçalho `X-MyEA-Automation: 1`
- Conta administrativa e HTTPS

## Instalação

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux: source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

## Uso
1. Entre com a URL HTTPS do backend, usuário e senha de administrador.
2. Selecione o JSON e a pasta raiz das mídias. Fotos devem ser caminhos relativos à pasta.
3. Em Configurar equipes, selecione os eletricistas e o veículo carregados do servidor.
4. Atribua uma equipe a cada demanda na tabela. Se a equipe divergir da demanda cadastrada, corrija no sistema.
5. Selecione demandas, valide e confirme as baixas aptas.
6. Exporte o relatório CSV.

O JSON é utilizado **apenas** para referência e fotos. Todos os demais dados vêm da API. A primeira foto é obrigatória; as demais são adicionais. Materiais planejados são enviados como utilizados nas mesmas quantidades.

## Build Windows

Execute em um computador/runner Windows:

```bash
pyinstaller --noconfirm --windowed --name MyEletricAssistent --collect-all PySide6 run.py
```

O executável ficará em `dist/MyEletricAssistent/`. Não embuta credenciais.

## Limitações e cuidados
- Não executa aprovação administrativa.
- Uma falha de rede após o envio pode deixar resultado incerto: consulte o sistema antes de tentar novamente.
- O cadastro e a edição das equipes não são persistidos; configure novamente a cada abertura.
- Fotos são aceitas em JPEG, PNG e WEBP, até 10 MB cada; até 12 por baixa no backend.
- Arquivos ZIP de mídia devem ser extraídos manualmente em diretório seguro antes da importação.
- O aplicativo não altera o cadastro de eletricistas ou veículos, apenas os consulta.
- Não foi realizado teste ponta a ponta com um servidor real neste ambiente.

## Atualizações via GitHub Releases (repositório público)

O botão **Verificar atualizações** consulta a última release, baixa o executável,
valida o SHA-256 informado pela API do GitHub, inicia um processo auxiliar do
Windows, faz backup `.previous` do executável e reinicia. Não interrompa uma
baixa em andamento para atualizar. O `.exe` deve estar em uma pasta com
permissão de escrita para o usuário (não em `Program Files` sem permissões).

1. Crie um repositório **público** no GitHub (não inclua segredos, senhas ou dados reais).
2. Envie o código, incluindo `.github/workflows/release.yml`.
3. Crie uma tag `v1.0.0` e faça push. O workflow gera e publica o `.exe`.
4. Distribua o `.exe` baixado de **Releases**. Ele já conterá a versão e o nome
   do repositório, inseridos automaticamente no build.
5. Para testar, altere o código, crie a tag `v1.0.1`, publique e abra a versão
   `1.0.0`. Clique em **Verificar atualizações**.

**Atenção:** a compilação local usa `GITHUB_REPOSITORY = ""` e mantém o botão
desabilitado até configurar `app/update_config.py`. O workflow de release injeta
o repositório automaticamente. Repositórios privados não funcionam com este
mecanismo sem autenticação. Não coloque tokens GitHub no executável.

A validação SHA-256 detecta corrupção/alteração do download, mas não substitui
assinatura digital do publicador. Faça primeiro o teste de atualização em uma
cópia de laboratório; arquivos em uso, antivírus ou falta de permissões podem
impedir a substituição. Em caso de falha, consulte
`%TEMP%\\MyEletricAssistent-update-error.log`.
