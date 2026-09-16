import os
import re
import subprocess
import shutil
from pathlib import Path
import pandas as pd
import streamlit as st

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
# BARRA LATERAL: CONFIGURACIÓN DE RUTAS
# ==============================================================================
st.sidebar.header("⚙️ Configuración del Sistema")

topas_exe = st.sidebar.text_input(
    "Ruta ejecutable TOPAS (tc.exe):",
    value=r"C:\Bruker\TOPAS6\tc.exe"
)

dir_libreria = st.sidebar.text_input(
    "Ruta librería local (.str):",
    value=r"./libreria_str"
)

dir_salida = st.sidebar.text_input(
    "Carpeta de salida de resultados:",
    value=r"./resultados_procesados"
)

# Detectar fases disponibles en la librería local
path_lib = Path(dir_libreria)
fases_disponibles = []
if path_lib.exists():
    fases_disponibles = [f.stem for f in path_lib.glob("*.str")]

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
    
    ' Parametros Instrumentales Estandar (Ajustar segun difractometro D8)
    CuKa1(1.540596)
    LP_Factor(26.4)
    Zero_Error(zero_err, 0.0)
    
    ' Ajuste de Fondo (Chebyshev)
    bkg @ 0.0 0.0 0.0 0.0
    
    ' Inclusion de Estructuras Cristalinas (.str)
    """
    for fase in fases_seleccionadas:
        path_str = path_libreria / f"{fase}.str"
        if path_str.exists():
            contenido += f'\n    #include "{path_str.resolve()}"'
    
    return contenido

def ejecutar_topas_muestra(topas_path: str, ruta_raw: Path, ruta_salida_dir: Path, fases: list, path_libreria: Path):
    """Crea el .inp, invoca a TOPAS tc.exe y retorna la ruta del .out."""
    nombre_base = ruta_raw.stem
    ruta_inp = ruta_salida_dir / f"{nombre_base}.inp"
    ruta_pro = ruta_salida_dir / f"{nombre_base}.pro"
    ruta_out = ruta_salida_dir / f"{nombre_base}.out"

    # 1. Crear archivo .inp
    contenido_inp = generar_contenido_inp(ruta_raw, ruta_pro, fases, path_libreria)
    with open(ruta_inp, "w", encoding="utf-8") as f:
        f.write(contenido_inp)

    # 2. Validar ejecutable
    if not os.path.exists(topas_path):
        return False, ruta_out, f"Ejecutable no encontrado en: {topas_path}"

    # 3. Invocar TOPAS en consola
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

    # Extracción de Rwp y GOF
    match_rwp = re.search(r"Rwp\s*=\s*([\d\.]+)", texto)
    match_gof = re.search(r"GOF\s*=\s*([\d\.]+)", texto)

    if match_rwp: 
        resultados["Rwp"] = float(match_rwp.group(1))
    if match_gof: 
        resultados["GOF"] = float(match_gof.group(1))

    # Extracción de % en peso por fase
    matches_fases = re.findall(r"phase_name\s+([^\s]+).*?weight_percent\s+([\d\.]+)", texto, re.DOTALL)
    for fase, peso in matches_fases:
        resultados[fase] = float(peso)

    # Criterio de validación
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
            "Selecciona las fases a refinar en este lote:",
            options=fases_disponibles,
            default=fases_disponibles[:3] if len(fases_disponibles) >= 3 else fases_disponibles
        )
    else:
        st.warning("⚠️ No se encontraron archivos `.str` en la librería indicada.")
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
            
            # Guardar archivo de muestra temporalmente
            ruta_raw_temp = path_salida / archivo_obj.name
            with open(ruta_raw_temp, "wb") as f:
                f.write(archivo_obj.getbuffer())
            
            # Ejecutar refinamiento en TOPAS
            exito, ruta_out, msg = ejecutar_topas_muestra(
                topas_exe, ruta_raw_temp, path_salida, fases_seleccionadas, path_lib
            )
            
            # Extraer datos del .out
            res = parsear_salida_topas(ruta_out, ruta_raw_temp.stem)
            if not exito and res["Estado"] == "Error":
                res["Estado"] = f"Error: {msg}"
                
            resultados_lote.append(res)
            progreso.progress((idx + 1) / len(archivos_cargados))
            
        status.success("¡Procesamiento por lote completado!")
        
        # --- TABLA DE RESULTADOS ---
        df_resultados = pd.DataFrame(resultados_lote)
        st.subheader("Resumen Cuantitativo (% en peso)")
        
        # Resaltar en rosa muestras con GOF > 2.5
        st.dataframe(
            df_resultados.style.highlight_between(
                left=2.5, right=100, subset=['GOF'], color='#ffcdd2'
            )
        )
        
        # Exportación a Excel
        excel_salida = path_salida / "Reporte_Cuantificacion.xlsx"
        df_resultados.to_excel(excel_salida, index=False)
        
        with open(excel_salida, "rb") as f:
            st.download_button(
                label="📥 Descargar Reporte Consolidado en Excel",
                data=f,
                file_name="Reporte_Cuantificacion_XRD.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
