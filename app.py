import os
import re
import subprocess
import shutil
from pathlib import Path
import pandas as pd
import streamlit as st

# Intentar importar tkinter para la ventana nativa de selección de carpetas
try:
    import tkinter as tk
    from tkinter import filedialog
    HAS_TKINTER = True
except ImportError:
    HAS_TKINTER = False

# ==============================================================================
# CONFIGURACIÓN DE PÁGINA STREAMLIT
# ==============================================================================
st.set_page_config(
    page_title="Geometallurgy XRD Automator",
    page_icon="⚡",
    layout="wide"
)

st.title("⚡ Automatizador de Cuantificación Mineralógica (Rietveld + TOPAS)")
st.markdown(
    "Procesamiento por lotes de patrones de difracción con exportación a Excel y archivos `.pro` para auditoría."
)

# ==============================================================================
# GESTIÓN DE ESTADO DE RUTAS (SESSION STATE)
# ==============================================================================
if "topas_exe" not in st.session_state:
    st.session_state["topas_exe"] = r"C:\Bruker\TOPAS6\tc.exe"

if "dir_libreria" not in st.session_state:
    st.session_state["dir_libreria"] = r"C:\DRX\Estructuras"

if "dir_salida" not in st.session_state:
    st.session_state["dir_salida"] = r"C:\DRX\Resultados"

def seleccionar_carpeta(key_state):
    """Abre un explorador de archivos nativo de Windows para seleccionar carpeta."""
    if HAS_TKINTER:
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost', 1)  # Mantiene la ventana al frente
        folder = filedialog.askdirectory(master=root)
        root.destroy()
        if folder:
            st.session_state[key_state] = os.path.normpath(folder)

def seleccionar_archivo_exe(key_state):
    """Abre un explorador de archivos nativo para seleccionar el ejecutable tc.exe."""
    if HAS_TKINTER:
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost', 1)  # Mantiene la ventana al frente
        file_path = filedialog.askopenfilename(
            master=root,
            title="Seleccionar ejecutable TOPAS (tc.exe)",
            filetypes=[("Ejecutable TOPAS", "tc.exe"), ("Todos los ejecutables", "*.exe")]
        )
        root.destroy()
        if file_path:
            st.session_state[key_state] = os.path.normpath(file_path)

# ==============================================================================
# BARRA LATERAL: CONFIGURACIÓN DE RUTAS Y BOTONES DE NAVEGACIÓN
# ==============================================================================
st.sidebar.header("⚙️ Configuración del Sistema")

# 1. Ruta TOPAS (tc.exe)
st.sidebar.subheader("1. Ejecutable TOPAS (tc.exe)")
col_exe1, col_exe2 = st.sidebar.columns([3, 1])
with col_exe1:
    topas_exe_input = st.text_input(
        "Ejecutable:",
        value=st.session_state["topas_exe"],
        key="topas_input",
        label_visibility="collapsed"
    )
    st.session_state["topas_exe"] = topas_exe_input
with col_exe2:
    if st.button("📁", key="btn_topas", help="Buscar tc.exe"):
        seleccionar_archivo_exe("topas_exe")
        st.rerun()

# 2. Ruta Librería (.str)
st.sidebar.subheader("2. Librería de Estructuras (.str)")
col_lib1, col_lib2 = st.sidebar.columns([3, 1])
with col_lib1:
    dir_lib_input = st.text_input(
        "Librería:",
        value=st.session_state["dir_libreria"],
        key="lib_input",
        label_visibility="collapsed"
    )
    st.session_state["dir_libreria"] = dir_lib_input
with col_lib2:
    if st.button("📁", key="btn_lib", help="Seleccionar carpeta de estructuras"):
        seleccionar_carpeta("dir_libreria")
        st.rerun()

# 3. Ruta Resultados
st.sidebar.subheader("3. Carpeta de Salida")
col_out1, col_out2 = st.sidebar.columns([3, 1])
with col_out1:
    dir_salida_input = st.text_input(
        "Salida:",
        value=st.session_state["dir_salida"],
        key="salida_input",
        label_visibility="collapsed"
    )
    st.session_state["dir_salida"] = dir_salida_input
with col_out2:
    if st.button("📁", key="btn_salida", help="Seleccionar carpeta de resultados"):
        seleccionar_carpeta("dir_salida")
        st.rerun()

# Asignación de variables desde el estado
topas_exe = st.session_state["topas_exe"]
dir_libreria = st.session_state["dir_libreria"]
dir_salida = st.session_state["dir_salida"]

# Detectar fases disponibles (.str y .cif)
path_lib = Path(dir_libreria)
fases_disponibles = []
if path_lib.exists():
    fases_disponibles = [f.stem for f in path_lib.glob("*.str")] + [f.stem for f in path_lib.glob("*.cif")]

# ==============================================================================
# FUNCIONES NUCLEARES DEL PIPELINE
# ==============================================================================
def generar_contenido_inp(ruta_raw: Path, ruta_pro: Path, fases_seleccionadas: list, path_libreria: Path) -> str:
    """Genera la estructura del archivo .inp para TOPAS."""
    contenido = f"""
    ' ==============================================================================
    ' ARCHIVO DE CONTROL GENERADO AUTOMATICAMENTE POR PYTHON
    ' ==============================================================================
    
    xdd "{ruta_raw.resolve()}"
    Out_PRO("{ruta_pro.resolve()}")
    
    ' Parametros Instrumentales Estandar
    CuKa1(1.540596)
    LP_Factor(26.4)
    Zero_Error(zero_err, 0.0)
    
    ' Ajuste de Fondo (Chebyshev)
    bkg @ 0.0 0.0 0.0 0.0
    
    ' Inclusion de Estructuras Cristalinas (.str / .cif)
    """
    for fase in fases_seleccionadas:
        path_str = path_libreria / f"{fase}.str"
        path_cif = path_libreria / f"{fase}.cif"
        if path_str.exists():
            contenido += f'\n    #include "{path_str.resolve()}"'
        elif path_cif.exists():
            contenido += f'\n    #include "{path_cif.resolve()}"'
    
    return contenido

def ejecutar_topas_muestra(topas_path: str, ruta_raw: Path, ruta_salida_dir: Path, fases: list, path_libreria: Path):
    """Crea el .inp, invoca a TOPAS tc.exe y retorna la ruta del .out."""
    nombre_base = ruta_raw.stem
    ruta_inp = ruta_salida_dir / f"{nombre_base}.inp"
    ruta_pro = ruta_salida_dir / f"{nombre_base}.pro"
    ruta_out = ruta_salida_dir / f"{nombre_base}.out"

    contenido_inp = generar_contenido_inp(ruta_raw, ruta_pro, fases, path_libreria)
    with open(ruta_inp, "w", encoding="utf-8") as f:
        f.write(contenido_inp)

    if not os.path.exists(topas_path):
        return False, ruta_out, f"Ejecutable no encontrado en: {topas_path}"

    try:
        cmd = [topas_path, str(ruta_inp)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode == 0:
            return True, ruta_out, "OK"
        else:
            return False, ruta_out, proc.stderr
    except Exception as e:
        return False, ruta_out, str(e)

def parsear_salida_topas(ruta_out: Path, nombre_muestra: str) -> dict:
    """Parsea el archivo .out generado para extraer Rwp, GOF y % en peso."""
    resultados = {"Muestra": nombre_muestra, "Rwp": None, "GOF": None, "Estado": "Error"}
    
    if not ruta_out.exists():
        resultados["Estado"] = "Archivo .out no generado"
        return resultados

    with open(ruta_out, 'r', encoding='utf-8', errors='ignore') as f:
        texto = f.read()

    match_rwp = re.search(r"Rwp\s*=\s*([\d\.]+)", texto)
    match_gof = re.search(r"GOF\s*=\s*([\d\.]+)", texto)

    if match_rwp: 
        resultados["Rwp"] = float(match_rwp.group(1))
    if match_gof: 
        resultados["GOF"] = float(match_gof.group(1))

    matches_fases = re.findall(r"phase_name\s+([^\s]+).*?weight_percent\s+([\d\.]+)", texto, re.DOTALL)
    for fase, peso in matches_fases:
        resultados[fase] = float(peso)

    if resultados["GOF"] is not None:
        resultados["Estado"] = "OK" if resultados["GOF"] < 2.5 else "Revisar Manualmente"

    return resultados

# ==============================================================================
# INTERFAZ PRINCIPAL
# ==============================================================================
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("1. Selección de Paragénesis Mineral")
    if fases_disponibles:
        fases_seleccionadas = st.multiselect(
            f"Selecciona las fases a refinar ({len(fases_disponibles)} detectadas):",
            options=fases_disponibles,
            default=fases_disponibles[:3] if len(fases_disponibles) >= 3 else fases_disponibles
        )
    else:
        st.warning(f"⚠️ No se encontraron archivos `.str` ni `.cif` en la ruta: {dir_libreria}")
        fases_seleccionadas = []

with col2:
    st.subheader("2. Carga de Difractogramas")
    archivos_cargados = st.file_uploader(
        "Sube tus archivos de muestra (.RAW o .XY):",
        accept_multiple_files=True,
        type=["raw", "xy"]
    )

# ==============================================================================
# EJECUCIÓN DEL PROCESAMIENTO
# ==============================================================================
st.markdown("---")

if st.button("🚀 Ejecutar Cuantificación Automática", type="primary"):
    if not archivos_cargados:
        st.error("Debes cargar al menos un archivo de difracción.")
    elif not fases_seleccionadas:
        st.error("Debes seleccionar al menos una fase mineral.")
    else:
        path_salida = Path(dir_salida)
        path_salida.mkdir(parents=True, exist_ok=True)
        
        resultados_lote = []
        progreso = st.progress(0)
        status = st.empty()
        
        for idx, archivo_obj in enumerate(archivos_cargados):
            status.text(f"Procesando ({idx+1}/{len(archivos_cargados)}): {archivo_obj.name}")
            
            ruta_raw_temp = path_salida / archivo_obj.name
            with open(ruta_raw_temp, "wb") as f:
                f.write(archivo_obj.getbuffer())
            
            exito, ruta_out, msg = ejecutar_topas_muestra(
                topas_exe, ruta_raw_temp, path_salida, fases_seleccionadas, path_lib
            )
            
            res = parsear_salida_topas(ruta_out, ruta_raw_temp.stem)
            if not exito and res["Estado"] == "Error":
                res["Estado"] = f"Error: {msg}"
                
            resultados_lote.append(res)
            progreso.progress((idx + 1) / len(archivos_cargados))
            
        status.success("¡Procesamiento por lote completado!")
        
        df_resultados = pd.DataFrame(resultados_lote)
        st.subheader("Resumen Cuantitativo (% en peso)")
        
        st.dataframe(
            df_resultados.style.highlight_between(
                left=2.5, right=100, subset=['GOF'], color='#ffcdd2'
            )
        )
        
        excel_salida = path_salida / "Reporte_Cuantificacion.xlsx"
        df_resultados.to_excel(excel_salida, index=False)
        
        with open(excel_salida, "rb") as f:
            st.download_button(
                label="📥 Descargar Reporte Consolidado en Excel",
                data=f,
                file_name="Reporte_Cuantificacion_XRD.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
