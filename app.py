import os
import re
import subprocess
from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Geometallurgy XRD Automator",
    page_icon="⚡",
    layout="wide"
)

st.title("⚡ Automatizador de Cuantificación Mineralógica (Rietveld + TOPAS)")
st.markdown("Procesamiento por lotes de patrones de difracción con exportación a Excel.")

# ==============================================================================
# BARRA LATERAL: CONFIGURACIÓN
# ==============================================================================
st.sidebar.header("⚙️ Configuración del Sistema")

topas_exe_input = st.sidebar.text_input(
    "1. Ruta ejecutable TOPAS (tc.exe):",
    value=r"C:\TOPAS5\tc.exe"
)

dir_salida_input = st.sidebar.text_input(
    "2. Carpeta de trabajo / salida local:",
    value=r"C:\DRX\Resultados"
)

path_topas = Path(topas_exe_input.strip('"').strip("'"))
path_salida = Path(dir_salida_input.strip('"').strip("'"))

st.sidebar.markdown("---")
st.sidebar.subheader("🔍 Diagnóstico")
st.sidebar.write(f"**TOPAS ejecutable detectado:** {path_topas.exists()}")

# ==============================================================================
# FUNCIONES
# ==============================================================================
def generar_contenido_inp(ruta_raw: Path, ruta_pro: Path, mapa_estructuras: dict) -> str:
    includes = [f'    #include "{path_str}"' for path_str in mapa_estructuras.values()]
    inc_text = "\n".join(includes)
    
    return f"""xdd "{ruta_raw.resolve()}"
Out_PRO("{ruta_pro.resolve()}")
CuKa1(1.540596)
LP_Factor(26.4)
Zero_Error(zero_err, 0.0)
bkg @ 0.0 0.0 0.0 0.0
{inc_text}
"""

def ejecutar_topas_muestra(topas_path: Path, ruta_raw: Path, ruta_salida_dir: Path, mapa_estructuras: dict):
    nombre_base = ruta_raw.stem
    ruta_inp = ruta_salida_dir / f"{nombre_base}.inp"
    ruta_pro = ruta_salida_dir / f"{nombre_base}.pro"
    ruta_out = ruta_salida_dir / f"{nombre_base}.out"

    contenido_inp = generar_contenido_inp(ruta_raw, ruta_pro, mapa_estructuras)
    with open(ruta_inp, "w", encoding="utf-8") as f:
        f.write(contenido_inp)

    if not topas_path.exists():
        return False, ruta_out, f"Ejecutable no encontrado en: {topas_path}"

    try:
        cmd = [str(topas_path), str(ruta_inp)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return (True, ruta_out, "OK") if proc.returncode == 0 else (False, ruta_out, proc.stderr)
    except Exception as e:
        return False, ruta_out, str(e)

def parsear_salida_topas(ruta_out: Path, nombre_muestra: str) -> dict:
    resultados = {"Muestra": nombre_muestra, "Rwp": None, "GOF": None, "Estado": "Error"}
    if not ruta_out.exists():
        resultados["Estado"] = "Archivo .out no generado"
        return resultados

    with open(ruta_out, 'r', encoding='utf-8', errors='ignore') as f:
        texto = f.read()

    match_rwp = re.search(r"Rwp\s*=\s*([\d\.]+)", texto)
    match_gof = re.search(r"GOF\s*=\s*([\d\.]+)", texto)

    if match_rwp: resultados["Rwp"] = float(match_rwp.group(1))
    if match_gof: resultados["GOF"] = float(match_gof.group(1))

    matches_fases = re.findall(r"phase_name\s+([^\s]+).*?weight_percent\s+([\d\.]+)", texto, re.DOTALL)
    for fase, peso in matches_fases:
        resultados[fase] = float(peso)

    if resultados["GOF"] is not None:
        resultados["Estado"] = "OK" if resultados["GOF"] < 2.5 else "Revisar Manualmente"

    return resultados

# ==============================================================================
# INTERFAZ PRINCIPAL DE CARGA
# ==============================================================================
col1, col2 = st.columns(2)

with col1:
    st.subheader("1. Carga de Estructuras (.STR / .CIF)")
    estructuras_cargadas = st.file_uploader(
        "Sube los archivos de tu librería mineralógica:",
        accept_multiple_files=True,
        type=["str", "cif"],
        key="uploader_estructuras"
    )

with col2:
    st.subheader("2. Carga de Difractogramas (.RAW / .XY)")
    muestras_cargadas = st.file_uploader(
        "Sube tus archivos de muestra:",
        accept_multiple_files=True,
        type=["raw", "xy"],
        key="uploader_muestras"
    )

st.markdown("---")

# ==============================================================================
# EJECUCIÓN
# ==============================================================================
if st.button("🚀 Ejecutar Cuantificación Automática", type="primary"):
    if not estructuras_cargadas:
        st.error("Debes cargar al menos una estructura (.str / .cif).")
    elif not muestras_cargadas:
        st.error("Debes cargar al menos un difractograma (.raw / .xy).")
    else:
        path_salida.mkdir(parents=True, exist_ok=True)
        
        # Guardar las estructuras cargadas temporalmente en la carpeta de trabajo
        mapa_estructuras = {}
        for est_obj in estructuras_cargadas:
            ruta_est_local = path_salida / est_obj.name
            with open(ruta_est_local, "wb") as f:
                f.write(est_obj.getbuffer())
            mapa_estructuras[Path(est_obj.name).stem] = str(ruta_est_local.resolve())

        resultados_lote = []
        progreso = st.progress(0)
        status = st.empty()
        
        for idx, muestra_obj in enumerate(muestras_cargadas):
            status.text(f"Procesando ({idx+1}/{len(muestras_cargadas)}): {muestra_obj.name}")
            
            ruta_raw_temp = path_salida / muestra_obj.name
            with open(ruta_raw_temp, "wb") as f:
                f.write(muestra_obj.getbuffer())
            
            exito, ruta_out, msg = ejecutar_topas_muestra(
                path_topas, ruta_raw_temp, path_salida, mapa_estructuras
            )
            
            res = parsear_salida_topas(ruta_out, ruta_raw_temp.stem)
            if not exito and res["Estado"] == "Error":
                res["Estado"] = f"Error: {msg}"
                
            resultados_lote.append(res)
            progreso.progress((idx + 1) / len(muestras_cargadas))
            
        status.success("¡Procesamiento por lote completado!")
        df_resultados = pd.DataFrame(resultados_lote)
        st.subheader("Resumen Cuantitativo (% en peso)")
        st.dataframe(df_resultados)
        
        excel_salida = path_salida / "Reporte_Cuantificacion.xlsx"
        df_resultados.to_excel(excel_salida, index=False)
        
        with open(excel_salida, "rb") as f:
            st.download_button(
                label="📥 Descargar Reporte Consolidado en Excel",
                data=f,
                file_name="Reporte_Cuantificacion_XRD.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
