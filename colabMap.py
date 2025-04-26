import requests
from bs4 import BeautifulSoup
from fuzzywuzzy import fuzz
import nltk
import json
from langdetect import detect

# Download the necessary NLTK data
nltk.download('punkt')
nltk.download('punkt_tab') # Download the missing punkt_tab data


# Função para traduzir palavras-chave usando MyMemory
def traduzir_keyword(kw):
    try:
        idioma = detect(kw)  # Detecta o idioma
        if idioma != 'pt':  # Se não for português, traduz
            url = f"https://api.mymemory.translated.net/get?q={kw}&langpair={idioma}|pt"
            response = requests.get(url).json()
            traducao = response.get("responseData", {}).get("translatedText", kw)
            return traducao.lower()
    except Exception as e:
        print(f"Erro ao processar keyword '{kw}': {e}")
    return kw.lower()

# Função para traduzir e filtrar keywords
def filtrar_e_traduzir_keywords(keywords):
    return [traduzir_keyword(kw.strip().lower()) for kw in keywords]

# Função para coletar os autores, título, link e keywords de um artigo
def get_article_data(article_url):
    authors = []
    keywords = []
    response = requests.get(article_url)
    soup = BeautifulSoup(response.content, 'html.parser')

    # Coleta o título do artigo
    title_tag = soup.find('h1', class_='page_title')
    article_title = title_tag.get_text(strip=True) if title_tag else 'Título não encontrado'

    # Coleta os autores
    authors_list = soup.find('ul', class_='item authors')
    if authors_list:
        for li in authors_list.find_all('li'):
            author_name = li.find('span', class_='name')
            if author_name:
                authors.append(author_name.get_text(strip=True))

    # Coleta as palavras-chave
    keywords_div = soup.find('div', class_='item keywords')
    if keywords_div:
        keywords_span = keywords_div.find('span', class_='value')
        if keywords_span:
            keywords = filtrar_e_traduzir_keywords([kw.strip() for kw in keywords_span.get_text().split(',')])

    return authors, article_title, article_url, keywords

# Função para acessar as edições e coletar os artigos e seus autores
def get_articles(urls):
    articles_data = []
    all_authors = []

    for base_url in urls:
        response = requests.get(base_url)
        soup = BeautifulSoup(response.content, 'html.parser')
        editions = soup.find_all('div', class_='obj_issue_summary')

        for edition in editions:
            edition_link = edition.find('a', class_='title')
            if edition_link:
                edition_url = edition_link['href']
                edition_response = requests.get(edition_url)
                edition_soup = BeautifulSoup(edition_response.content, 'html.parser')
                articles = edition_soup.find_all('div', class_='obj_article_summary')
                for article in articles:
                    article_link = article.find('a')
                    if article_link:
                        article_url = article_link['href']
                        authors, title, url, keywords = get_article_data(article_url)
                        if authors:
                            articles_data.append({"authors": authors, "title": title, "url": url, "keywords": keywords})
                            all_authors.extend(authors)

    return articles_data, all_authors

# O restante do código permanece inalterado...


# Função para comparar nomes de forma mais rigorosa
def nomes_similares(nome1, nome2):
    tokens1 = nltk.word_tokenize(nome1)
    tokens2 = nltk.word_tokenize(nome2)

    if len(tokens1) < 2 or len(tokens2) < 2:
        return False

    primeiro_ultimo_igual = (tokens1[0] == tokens2[0]) and (tokens1[-1] == tokens2[-1])
    similaridade_fuzzy = fuzz.ratio(nome1, nome2) > 90

    return primeiro_ultimo_igual or similaridade_fuzzy


# Filtragem de nomes
def filtrar_nomes_v3(nomes):
    nomes_unicos = []
    nomes_variantes = {}

    for nome in nomes:
        encontrado = False
        for nome_filtrado in nomes_unicos:
            if nomes_similares(nome, nome_filtrado):
                nomes_variantes.setdefault(nome_filtrado, []).append(nome)
                encontrado = True
                break
        if not encontrado:
            nomes_unicos.append(nome)
            nomes_variantes[nome] = [nome]

    return nomes_unicos, nomes_variantes


# Substituição dos nomes corrigidos
def substituir_nomes(articles_data, nomes_variantes):
    artigos_corrigidos = []
    for artigo in articles_data:
        artigo_corrigido = {"authors": [], "title": artigo["title"], "url": artigo["url"], "keywords": artigo["keywords"]}
        for autor in artigo["authors"]:
            nome_correspondente = next(
                (nome_base for nome_base, variantes in nomes_variantes.items() if autor in variantes), autor)
            artigo_corrigido["authors"].append(nome_correspondente)
        artigos_corrigidos.append(artigo_corrigido)
    return artigos_corrigidos


# Função para criar o grafo de coautoria (nodes e links)
def criar_grafo_json(artigos):
    nodes = []
    links = []
    coautorias = {}

    # Adiciona os nós (autores) ao grafo
    autores = set()
    for artigo in artigos:
        for autor in artigo["authors"]:
            autores.add(autor)

    # Adiciona os nós ao JSON
    nodes = [{"id": autor} for autor in autores]

    # Contabiliza os artigos compartilhados entre os autores
    for artigo in artigos:
        for i in range(len(artigo["authors"])):
            for j in range(i + 1, len(artigo["authors"])):
                autor1 = artigo["authors"][i]
                autor2 = artigo["authors"][j]
                # Garante que a tupla (autor1, autor2) seja sempre armazenada de forma ordenada
                key = tuple(sorted([autor1, autor2]))
                if key not in coautorias:
                    coautorias[key] = 0
                coautorias[key] += 1

    # Cria os links (coautorias)
    for (autor1, autor2), count in coautorias.items():
        links.append({
            "source": autor1,
            "target": autor2,
            "articles_in_common": count  # Adiciona o número de artigos em comum
        })

    # Estrutura do grafo em formato JSON
    grafo_json = {
        "nodes": nodes,
        "links": links
    }

    # Salva o grafo em um arquivo JSON
    with open('grafo_coautoria.json', 'w') as json_file:
        json.dump(grafo_json, json_file, indent=4)

    return grafo_json


# Função para criar o arquivo JSON com os autores filtrados e seus respectivos artigos
def criar_json_autores_artigos(artigos, nomes_variantes):
    autores_artigos = {}

    # Processa os artigos e associa aos autores os respectivos títulos, links e keywords
    for artigo in artigos:
        titulo = artigo["title"]
        url = artigo["url"]
        keywords = artigo.get("keywords", [])  # Garantir que as keywords sejam uma lista, caso existam
        for autor in artigo["authors"]:
            # Verifica o nome filtrado (padronizado)
            autor_filtrado = next((nome_base for nome_base, variantes in nomes_variantes.items() if autor in variantes), autor)

            if autor_filtrado not in autores_artigos:
                autores_artigos[autor_filtrado] = []

            # Adiciona o título, o link e as keywords ao autor
            autores_artigos[autor_filtrado].append({
                "title": titulo,
                "url": url,
                "keywords": keywords  # Inclui as keywords do artigo
            })

    # Estrutura final dos dados para o JSON
    autores_json = [{"author": autor, "articles": artigos} for autor, artigos in autores_artigos.items()]

    # Salva o resultado no arquivo JSON
    with open('autores_artigos_com_artigos.json', 'w') as json_file:
        json.dump(autores_json, json_file, indent=4)

    return autores_json


# Exemplo de chamada final
urls = [
    "https://sol.sbc.org.br/index.php/sbsc/issue/archive",
    "https://sol.sbc.org.br/index.php/sbsc_estendido/issue/archive"
]
articles_data, all_authors = get_articles(urls)
nomes_filtrados, nomes_variantes = filtrar_nomes_v3(all_authors)
artigos_corrigidos = substituir_nomes(articles_data, nomes_variantes)

# Gerar o grafo de coautoria
criar_grafo_json(artigos_corrigidos)

# Gerar o arquivo JSON com autores e seus artigos, incluindo keywords
criar_json_autores_artigos(artigos_corrigidos, nomes_variantes)
