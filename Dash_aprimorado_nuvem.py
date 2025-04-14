import streamlit as st
import pandas as pd
import plotly.express as px
from fpdf import FPDF
import tempfile
import os
import chardet
import smtplib
from email.message import EmailMessage
import json
from pathlib import Path
import base64

# Caminho do arquivo de configuração do SMTP
CONFIG_PATH = Path(os.path.join(os.path.dirname(__file__), "smtp_config.json"))

# Função para carregar a configuração salva
def carregar_configuracao():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    return {}

# Função para salvar configuração
def salvar_configuracao(config):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f)

# Função para carregar dados com detecção de separador, encoding e extensão
def carregar_dados(arquivo):
    nome_arquivo = arquivo.name.lower()
    if nome_arquivo.endswith('.csv') or nome_arquivo.endswith('.txt'):
        resultado = chardet.detect(arquivo.read(1024))
        arquivo.seek(0)
        encoding_detectado = resultado['encoding'] or 'utf-8'

        primeira_linha = arquivo.readline().decode(encoding_detectado)
        delimitador = ',' if primeira_linha.count(',') > primeira_linha.count(';') else ';'
        arquivo.seek(0)

        df = pd.read_csv(arquivo, sep=delimitador, encoding=encoding_detectado)
    elif nome_arquivo.endswith('.xls') or nome_arquivo.endswith('.xlsx'):
        df = pd.read_excel(arquivo)
    else:
        st.error("Formato de arquivo não suportado. Envie CSV, TXT, XLS ou XLSX.")
        return None

    df.columns = df.columns.str.strip()
    df = df.loc[:, ~df.columns.duplicated()]
    return df

# Função para gerar gráfico de barras com porcentagens
def grafico_barra_percentual(df, coluna, titulo):
    contagem = df[coluna].value_counts().reset_index()
    contagem.columns = [coluna, 'count']
    contagem['percent'] = (contagem['count'] / contagem['count'].sum() * 100).round(2)
    fig = px.bar(contagem, x=coluna, y='count', color=coluna,
                 text=contagem['percent'].astype(str) + '%',
                 title=titulo, labels={coluna: coluna, 'count': 'Quantidade'})
    fig.update_traces(textposition='outside')
    fig.update_layout(uniformtext_minsize=8, uniformtext_mode='hide')
    return fig

# Função para gerar gráfico de pizza com porcentagens
def grafico_pizza_percentual(df, coluna, titulo):
    contagem = df[coluna].value_counts().reset_index()
    contagem.columns = [coluna, 'count']
    contagem['percent'] = (contagem['count'] / contagem['count'].sum() * 100).round(2)
    fig = px.pie(contagem, names=coluna, values='count',
                 title=titulo, hole=0.3,
                 labels={coluna: coluna},
                 color_discrete_sequence=px.colors.qualitative.Set3)
    fig.update_traces(textinfo='percent+label')
    return fig

# Função para exportar para PDF
def gerar_pdf(figs, tabela):
    temp_dir = tempfile.mkdtemp()  # Usando mkdtemp para criar um diretório temporário
    pdf_path = os.path.join(temp_dir, "relatorio_temp.pdf")
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="Painel Inteligente de Indicadores Técnicos", ln=True, align='C')

    for fig in figs:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
            fig.write_image(tmp_img.name, width=800, height=500, scale=2)
            pdf.image(tmp_img.name, x=10, y=None, w=190)
            os.unlink(tmp_img.name)

    pdf.add_page()
    pdf.set_font("Arial", size=10)
    for index, row in tabela.iterrows():
        linha = " | ".join([f"{col}: {row[col]}" for col in tabela.columns if pd.notnull(row[col])])
        pdf.multi_cell(0, 10, linha)

    pdf.output(pdf_path)
    return pdf_path

# Função para enviar e-mail com anexo PDF
def enviar_email(smtp_server, smtp_port, email_remetente, senha, email_destinatario, caminho_pdf):
    msg = EmailMessage()
    msg['Subject'] = 'Relatório Automático do Dashboard'
    msg['From'] = email_remetente
    msg['To'] = email_destinatario
    msg.set_content("Segue em anexo o relatório gerado automaticamente.")

    with open(caminho_pdf, 'rb') as f:
        file_data = f.read()
        msg.add_attachment(file_data, maintype='application', subtype='pdf', filename='relatorio_dados.pdf')

    with smtplib.SMTP(smtp_server, smtp_port) as smtp:
        smtp.starttls()
        smtp.login(email_remetente, senha)
        smtp.send_message(msg)

# Configuração do app Streamlit
st.set_page_config(page_title="Painel Inteligente de Indicadores Técnicos", layout="wide")
st.title("Painel Inteligente de Indicadores Técnicos")

# Upload de arquivo
arquivo = st.file_uploader("Selecione um arquivo (CSV, TXT, XLS, XLSX)", type=["csv", "txt", "xls", "xlsx"])

colunas_remover = [
    'ID do Líder do Projeto', 'ID do responsável', 'ID do relator', 'ID do criador',
    'Grafico de distribuição - Descrição', 'Seguidores.2', 'ID dos Seguidores',
    'ID dos seguidores.1', 'ID dos seguidores.2', 'Anexo.1', 'Anexo.2', 'Anexo.3',
    'Campo personalizado(Aprovals)'
]

if arquivo:
    df = carregar_dados(arquivo)

    if df is not None:
        df = df.drop(columns=[col for col in colunas_remover if col in df.columns], errors='ignore')
        colunas_objetivas = [col for col in df.columns if df[col].dtype == 'object' and df[col].nunique() < 50]

        st.sidebar.markdown("### Filtros")
        colunas_filtradas = st.sidebar.multiselect("Ativar filtros para colunas:", colunas_objetivas, default=[])

        for coluna in colunas_filtradas:
            valores = df[coluna].dropna().unique().tolist()
            selecao = st.sidebar.multiselect(f"{coluna}", ["Todos"] + valores, default=["Todos"])
            if "Todos" not in selecao:
                df = df[df[coluna].isin(selecao)]

        for coluna in colunas_filtradas:
            st.subheader(f"Gráfico de Distribuição - {coluna}")
            try:
                fig_barra = grafico_barra_percentual(df, coluna, f'Distribuição de {coluna}')
                st.plotly_chart(fig_barra, use_container_width=True)
            except:
                st.warning(f"Não foi possível gerar gráfico de barras para a coluna: {coluna}")

            try:
                fig_pizza = grafico_pizza_percentual(df, coluna, f'Distribuição de {coluna} (Pizza)')
                st.plotly_chart(fig_pizza, use_container_width=True)
            except:
                st.warning(f"Não foi possível gerar gráfico de pizza para a coluna: {coluna}")

        st.markdown("### Tabela Completa dos Dados")
        st.dataframe(df, height=400)

        st.markdown("---")
        st.markdown("### Configuração de E-mail para envio de relatório")

        config_salva = carregar_configuracao()

        lembrar = st.checkbox("Lembrar estas configurações", value=True)

        smtp_server = st.text_input("Servidor SMTP", value=config_salva.get("smtp_server", "smtp.gmail.com"))
        smtp_port = st.number_input("Porta SMTP", value=config_salva.get("smtp_port", 587))
        email_remetente = st.text_input("E-mail do remetente", value=config_salva.get("email_remetente", ""))
        senha = st.text_input("Senha do remetente", type="password")
        email_destinatario = st.text_input("E-mail do destinatário", value=config_salva.get("email_destinatario", ""))

        if st.button("Gerar Relatório PDF e Enviar por E-mail"):
            figs = []
            for coluna in colunas_filtradas:
                try:
                    figs.append(grafico_pizza_percentual(df, coluna, f'{coluna} (Pizza)'))
                except:
                    continue
            caminho_pdf = gerar_pdf(figs, df)
            try:
                enviar_email(smtp_server, smtp_port, email_remetente, senha, email_destinatario, caminho_pdf)
                st.success("Relatório enviado com sucesso!")
                if lembrar:
                    salvar_configuracao({
                        "smtp_server": smtp_server,
                        "smtp_port": smtp_port,
                        "email_remetente": email_remetente,
                        "email_destinatario": email_destinatario
                    })
            except Exception as e:
                st.error(f"Erro ao enviar e-mail: {e}")

        if st.button("Exportar para PDF Manualmente"):
            figs = []
            for coluna in colunas_filtradas:
                try:
                    figs.append(grafico_pizza_percentual(df, coluna, f'{coluna} (Pizza)'))
                except:
                    continue
            caminho_pdf = gerar_pdf(figs, df)
            with open(caminho_pdf, "rb") as f:
                pdf_data = f.read()
            b64 = base64.b64encode(pdf_data).decode()
            href = f'<a href="data:application/octet-stream;base64,{b64}" download="relatorio_dados.pdf">Clique aqui para baixar o PDF</a>'
            st.markdown(href, unsafe_allow_html=True)

else:
    st.info("Aguardando o upload de um arquivo de dados para exibir o dashboard.")
