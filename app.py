import os
import re
import subprocess
from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Geometallurgy XRD Automator", layout="wide")

st.title("⚡ Automatizador de Cuantificación Mineralógica (Rietveld + TOPAS)")

# BARRA LATERAL
st.sidebar.header("⚙️ Configuración")
topas_exe = st.sidebar.text_input("1. Ruta ejecutable TOPAS (tc.exe):", value=r"C:\Bruker\TOPAS6\tc.exe")
dir_libreria = st.sidebar.text_input("2. Ruta librería local (.str / .cif):", value=r"C:\DRX\Estructuras")
dir_salida = st.sidebar.text_input("3. Carpeta de salida:", value=r"C:\DRX\Resultados")

# DETECCIÓN DE FASES
path_lib = Path(dir_libreria)
fases_disponibles = []
if path_lib.exists():
    fases_disponibles = sorted([f.stem for f in path_lib.glob("*.str")] + [f.stem for f in path_lib.glob("*.cif")])

# FUNCIONES
def generar_inp(ruta_raw, ruta_pro, fases, path_lib):
    inc = "\n".join([f'    #include "{(path_lib/f"{f}.str").resolve()}"' if (path_lib/f"{f}.str").exists() else f'    #include "{(path_lib/f"{f}.cif").resolve()}"' for f in fases])
    return f"""xdd "{ruta_raw.resolve()}"\nOut_PRO("{ruta_pro.resolve()}")\nCuKa1(1.540596)\nLP_Factor(26.4)\nZero_Error(zero_err, 0.0)\nbkg @ 0.0 0.0 0.0 0.0\n{inc}"""

def ejecutar_topas(topas_path, ruta_raw, ruta_salida, fases, path_lib):
    n_base = ruta_raw.stem
    r_inp, r_pro, r_out = ruta_salida/f"{n_base}.inp", ruta_salida/f"{n_base}.pro", ruta_salida/f"{n_base}.out"
    with open(r_inp, "w", encoding="utf-8") as f:
        f.write(generar_inp(ruta_raw, r_pro, fases, path_lib))
    if not os.path.exists(topas_path):
        return False, r_out, "TOPAS no encontrado"
    try:
        proc = subprocess.run([topas_path, str(r_inp)], capture_output=True, text=True, timeout=120)
        return proc.returncode == 0, r_out, "OK" if proc.returncode == 0 else proc.stderr
    except Exception as e:
        return False, r_out, str(e)

def parsear_out(ruta_out, muestra):
    res = {"Muestra": muestra, "Rwp": None, "GOF": None, "Estado": "Error"}
    if not ruta_out.exists(): return res
    texto = ruta_out.read_text(encoding='utf-8', errors='ignore')
    m_rwp, m_gof = re.search(r"Rwp\s*=\s*([\d\.]+)", texto), re.search(r"GOF\s*=\s*([\d\.]+)", texto)
    if m_rwp: res["Rwp"] = float(m_rwp.group(1))
    if m_gof: res["GOF"] = float(m_gof.group(1))
    for f, p in re.findall(r"phase_name\s+([^\s]+).*?weight_percent\s+([\d\.]+)", texto, re.DOTALL):
        res[f] = float(p)
    if res["GOF"] is not None: res["Estado"] = "OK" if res["GOF"] < 2.5 else "Revisar"
    return res

# INTERFAZ
col1, col2 = st.columns(2)
with col1:
    st.subheader("1. Selección de Paragénesis")
    fases_sel = st.multiselect("Fases a refinar:", options=fases_disponibles, default=fases_disponibles[:3] if fases_disponibles else [])
with col2:
    st.subheader("2. Archivos DRX")
    archivos = st.file_uploader("Subir muestras (.RAW / .XY):", accept_multiple_files=True, type=["raw", "xy"])

# BOTÓN PRINCIPAL
st.divider()
if st.button("🚀 Ejecutar Cuantificación Automática", type="primary"):
    if not archivos:
        st.error("Sube al menos un archivo.")
    elif not fases_sel:
        st.error("Selecciona al menos una fase.")
    else:
        path_salida = Path(dir_salida)
        path_salida.mkdir(parents=True, exist_ok=True)
        
        lote = []
        bar = st.progress(0)
        
        for idx, obj in enumerate(archivos):
            r_temp = path_salida / obj.name
            r_temp.write_bytes(obj.getbuffer())
            ex, r_out, msg = ejecutar_topas(topas_exe, r_temp, path_salida, fases_sel, path_lib)
            r = parsear_out(r_out, r_temp.stem)
            if not ex and r["Estado"] == "Error": r["Estado"] = msg
            lote.append(r)
            bar.progress((idx + 1) / len(archivos))
            
        df = pd.DataFrame(lote)
        st.dataframe(df)
        
        excel_path = path_salida / "Reporte_Cuantificacion.xlsx"
        df.to_excel(excel_path, index=False)
        st.download_button("📥 Descargar Excel", data=open(excel_path, "rb"), file_name="Reporte_XRD.xlsx")
