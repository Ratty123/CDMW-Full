"""Spanish About documentation content."""

from __future__ import annotations

from html import escape
from typing import Dict, List, Tuple

from cdmw.constants import APP_TITLE, APP_VERSION


class AboutDocumentationSpanishMixin:
    """Spanish documentation topic content."""

    def _build_about_document_for_spanish(self) -> Tuple[str, str, List[Dict[str, str]]]:
        title = f"Documentacion de {APP_TITLE}"
        intro_html = f"""
        <p><b>{APP_TITLE} v{APP_VERSION}</b> es una herramienta de escritorio para explorar archivos de Crimson Desert, previsualizar recursos, reconstruir DDS, editar texturas visibles, preparar reemplazos, investigar familias de archivos y buscar texto.</p>
        <p>Usa la busqueda y la lista de temas de la izquierda, o abre directamente:
        <a href="topic:quick_start">Inicio rapido</a>,
        <a href="topic:first_run_checklist">Lista de primera ejecucion</a>,
        <a href="topic:workflow_overview">Flujo de texturas</a>,
        <a href="topic:workflow_profiles">Perfiles de flujo</a>,
        <a href="topic:workflow_rules">Reglas ordenadas</a>,
        <a href="topic:workflow_planner_profiles">Perfiles del planificador</a>,
        <a href="topic:workflow_planner_paths">Rutas del planificador</a>,
        <a href="topic:texture_workflow_guides">Guias del flujo de texturas</a>,
        <a href="topic:compare_review">Comparar y revisar</a>,
        <a href="topic:archive_browser">Explorador de archivos</a>,
        <a href="topic:mesh_media_guides">Importacion e intercambio de mallas</a>,
        <a href="topic:texture_editor">Editor de texturas</a>,
        <a href="topic:replace_assistant">Asistente de reemplazo</a>,
        <a href="topic:research">Investigacion</a>,
        <a href="topic:text_search">Busqueda de texto</a>,
        <a href="topic:mod_packaging">Empaquetado mod-ready</a>,
        <a href="topic:profile_settings">Perfil y configuracion</a>,
        <a href="topic:window_layout">Ventana y layout</a>,
        <a href="topic:safety">Seguridad</a>,
        <a href="topic:faq">FAQ</a>,
        <a href="topic:troubleshooting">Solucion de problemas</a>.
        </p>
        """
        settings_text = escape(str(self.settings_file_path))
        cache_text = escape(str(self.archive_cache_root))
        sections = [
            {
                "id": "overview",
                "title": "Vista general",
                "summary": "Resumen de las areas principales de la aplicacion.",
                "keywords": "vista general funciones pestanas archivo flujo editor reemplazo investigacion busqueda configuracion",
                "html": """
                <p>La aplicacion esta dividida en areas de trabajo para que no tengas que usar una sola tuberia para todo.</p>
                <ul>
                  <li><b>Panel</b>: estado del workspace, rutas de herramientas, trabajo reciente y ultimo resultado con accesos a salida, Comparar y logs.</li>
                  <li><b>Flujo de texturas</b>: proceso por lotes para DDS sueltos, escalado opcional, reconstruccion DDS, comparacion y exportacion mod-ready.</li>
                  <li><b>Explorador de archivos</b>: escaneo, filtro, vista previa, extraccion, exportacion suelta y parches compatibles.</li>
                  <li><b>Biblioteca de modelos</b>: escaneo de modelos locales/importables, vista previa y envio a flujos del explorador.</li>
                  <li><b>Creador de iconos</b>: prepara imagenes fuente y paquetes compatibles para iconos de items.</li>
                  <li><b>Editor de texturas</b>: edicion por capas de texturas visibles y envio directo al flujo.</li>
                  <li><b>Asistente de reemplazo</b>: reemplazos guiados para PNG/DDS editados.</li>
                  <li><b>Investigacion</b>: familias DDS, clasificacion, referencias, analisis y notas.</li>
                  <li><b>Busqueda de texto</b>: busqueda en archivos de texto de archivo o sueltos.</li>
                  <li><b>Perfil, configuracion y ventana</b>: exportacion/importacion completa de preferencias, idioma, rendimiento, vista 3D y pestanas separables.</li>
                </ul>
                """,
            },
            {
                "id": "first_run_checklist",
                "title": "Lista de primera ejecucion",
                "summary": "Checklist de rutas, herramientas, politica y primera salida de prueba.",
                "keywords": "primera ejecucion checklist setup rutas texconv workspace ncnn chainner politica vista comparar",
                "html": """
                <ol>
                  <li>Abre <b>Configuracion</b> y ejecuta <b>Inicializar espacio</b> si quieres que la app cree las carpetas normales de trabajo.</li>
                  <li><b>Ruta de texconv.exe</b> es solo fallback legacy opcional. Vista DDS, conversion DDS-a-PNG, Comparar y reconstruccion DDS usan primero DirectXTex/native.</li>
                  <li>Define <b>Raiz DDS original</b>, <b>Raiz PNG</b> y <b>Raiz de salida</b>. Empieza con una carpeta de prueba pequena.</li>
                  <li>Elige backend de escalado: <b>Desactivado</b> para probar reconstruccion, <b>Real-ESRGAN NCNN</b> directo para escalado dentro de la app o <b>chaiNNer</b> para una cadena ya probada.</li>
                  <li>Manten un preajuste seguro de <b>Politica de texturas</b> y deja activas las reglas automaticas.</li>
                  <li>Revisa <b>Perfiles de flujo</b>, <b>Reglas ordenadas</b> y <b>Archivos coincidentes</b> si necesitas anulaciones por archivo.</li>
                  <li>Usa <b>Vista de politica</b> antes de <b>Iniciar</b> para confirmar que hara el planificador.</li>
                  <li>Ejecuta <b>Escanear</b>, procesa un lote pequeno y revisa en <b>Comparar</b>.</li>
                  <li>Amplia el filtro o la raiz de origen solo despues de que el lote pequeno se vea correcto.</li>
                </ol>
                <p>Si algo falla, abre <a href="topic:troubleshooting">Solucion de problemas y limites</a> y revisa el registro en vivo antes de cambiar muchas opciones a la vez.</p>
                """,
            },
            {
                "id": "workflow_overview",
                "title": "Flujo de texturas",
                "summary": "Pestana principal para procesar DDS sueltos por lotes.",
                "keywords": "flujo texturas lote dds png reconstruir comparar iniciar escanear politica resumen",
                "html": """
                <p>El flujo de texturas escanea los DDS bajo la raiz original, decide que hacer con cada archivo, crea PNG intermedios si hace falta, ejecuta el escalado opcional y reconstruye los DDS finales.</p>
                <ol>
                  <li>Configura <b>Configuracion / Setup</b>, <b>Configuracion / Rutas</b> y <b>Salida DDS</b>.</li>
                  <li>Revisa perfiles, reglas y archivos coincidentes.</li>
                  <li>Elige el backend de escalado o deja el escalado desactivado.</li>
                  <li>Usa la vista de politica para revisar el plan por archivo.</li>
                  <li>Ejecuta el proceso y revisa el resultado en Comparar.</li>
                </ol>
                """,
            },
            {
                "id": "workflow_profiles",
                "title": "Perfiles de flujo",
                "summary": "Conjuntos reutilizables de anulaciones por archivo.",
                "keywords": "perfiles flujo accion formato tamano mips ncnn escala tile correccion",
                "html": """
                <p>Los perfiles de flujo son ajustes reutilizables asignados por reglas. Los campos vacios heredan la configuracion global actual.</p>
                <ul>
                  <li><b>Accion</b>: permite heredar la decision del planificador o forzar reconstruccion, escalado, preservacion o salto.</li>
                  <li><b>Formato, tamano y mipmaps DDS</b>: cambian la salida para los archivos que coinciden.</li>
                  <li><b>Opciones NCNN</b>: modelo, escala, tile, argumentos extra y correccion posterior para Real-ESRGAN NCNN directo.</li>
                  <li><b>Perfiles iniciales</b>: puntos de partida seguros para color, normal, altura y especular.</li>
                </ul>
                """,
            },
            {
                "id": "workflow_rules",
                "title": "Reglas ordenadas",
                "summary": "Tabla de coincidencias donde gana la ultima regla valida.",
                "keywords": "reglas glob ruta exacta perfil semantica planificador colores alpha",
                "html": """
                <p>Las reglas se evaluan de arriba hacia abajo y gana la ultima coincidencia. Esto permite reglas amplias arriba y correcciones concretas al final.</p>
                <ul>
                  <li><b>Coincidencia</b>: glob para patrones o ruta exacta para un archivo concreto.</li>
                  <li><b>Perfil de flujo</b>: asigna el comportamiento reutilizable.</li>
                  <li><b>Semantica</b>: fuerza un significado tecnico si la inferencia no basta.</li>
                  <li><b>Perfil y ruta del planificador</b>: cambian las suposiciones tecnicas del plan para esa familia.</li>
                </ul>
                """,
            },
            {
                "id": "workflow_planner_profiles",
                "title": "Perfiles del planificador",
                "summary": "Perfiles tecnicos que guian formato, color, alpha y preservacion.",
                "keywords": "planificador perfiles color normal mascara scalar vector alpha preservar",
                "html": """
                <p>Un perfil del planificador define las suposiciones tecnicas para una textura: espacio de color, compresion esperada, alpha, mipmaps y si debe preservarse antes de modificarla.</p>
                <ul>
                  <li><code>color_default</code>: texturas visibles de color.</li>
                  <li><code>normal_bc5</code>: mapas normales, lineales y de preservacion prioritaria.</li>
                  <li><code>scalar_bc4</code>: mascaras o datos escalares.</li>
                  <li><code>packed_mask_preserve_layout</code>: canales empaquetados que no deben mezclarse.</li>
                  <li><code>float_or_vector_preserve_only</code>: datos de precision que deben conservarse.</li>
                </ul>
                """,
            },
            {
                "id": "workflow_planner_paths",
                "title": "Rutas del planificador",
                "summary": "Ruta intermedia preferida para cada archivo coincidente.",
                "keywords": "rutas planificador png visible tecnico preservar alta precision",
                "html": """
                <p>La ruta del planificador decide si una textura debe pasar por la ruta PNG visible o por una ruta tecnica mas conservadora.</p>
                <ul>
                  <li><code>visible_color_png_path</code>: adecuada para color visible y salidas revisables.</li>
                  <li><code>technical_preserve_path</code>: mantiene el archivo original cuando modificarlo es demasiado arriesgado.</li>
                  <li><code>technical_high_precision_path</code>: usa una ruta tecnica cuando hay datos de alta precision compatibles.</li>
                </ul>
                <p>Forzar mapas tecnicos por la ruta visible puede producir cambios de brillo, canales rotos o resultados inutilizables.</p>
                """,
            },
            {
                "id": "workflow_matched_files",
                "title": "Archivos coincidentes",
                "summary": "Vista viva de los DDS afectados por reglas y filtros actuales.",
                "keywords": "archivos coincidentes perfil regla accion dds ncnn filtro",
                "html": """
                <p>La tabla muestra los DDS bajo la raiz original que pasan el filtro actual y que ya tienen una accion calculada.</p>
                <ul>
                  <li><b>Ruta</b>: ubicacion relativa del DDS.</li>
                  <li><b>Semantica</b>: tipo inferido o forzado.</li>
                  <li><b>Regla</b>: ultima regla que coincide.</li>
                  <li><b>Accion</b>: resultado final combinado por reglas, perfil, backend y seguridad.</li>
                </ul>
                """,
            },
            {
                "id": "dds_output",
                "title": "Salida DDS y staging",
                "summary": "Valores globales usados al reconstruir DDS.",
                "keywords": "dds salida formato tamano mipmaps staging texconv png",
                "html": """
                <p>Salida DDS define los valores globales para archivos sin anulacion de perfil.</p>
                <ul>
                  <li><b>Formato</b>: conservar el formato original o forzar uno compatible con texconv.</li>
                  <li><b>Tamano</b>: usar tamano PNG, tamano original o tamano personalizado.</li>
                  <li><b>Mipmaps</b>: conservar, generar cadena completa, usar uno o fijar un recuento.</li>
                  <li><b>Staging DDS</b>: crea PNG intermedios antes de ejecutar un backend externo.</li>
                </ul>
                """,
            },
            {
                "id": "upscaling_backends",
                "title": "Escalado y backends",
                "summary": "Diferencias entre desactivado, NCNN directo y chaiNNer.",
                "keywords": "escalado backend ncnn chainner desactivado escala tile correccion",
                "html": """
                <p>El escalado puede estar desactivado, usar Real-ESRGAN NCNN directo o delegar el trabajo a chaiNNer.</p>
                <ul>
                  <li><b>Desactivado</b>: reconstruye DDS desde PNG existentes sin escalar.</li>
                  <li><b>Real-ESRGAN NCNN</b>: backend directo con modelo, escala, tile y correccion posterior.</li>
                  <li><b>chaiNNer</b>: flujo externo donde la cadena decide el procesamiento real.</li>
                </ul>
                <p>Las reglas automaticas siguen aplicandose aunque el backend de escalado este activo.</p>
                """,
            },
            {
                "id": "texture_workflow_guides",
                "title": "Guias del flujo de texturas",
                "summary": "Recetas para reconstruccion DDS, escalado y perfiles.",
                "keywords": "flujo texturas guias receta reconstruir escalar ncnn chainner dds staging perfil regla ruta exacta",
                "html": """
                <h4>Reconstruir DDS sin escalado</h4>
                <ol>
                  <li>Define <b>Raiz DDS original</b>, <b>Raiz PNG</b> y <b>Raiz de salida</b>. La ruta de <b>texconv.exe</b> es fallback opcional.</li>
                  <li>Configura backend como <b>Desactivado</b>.</li>
                  <li>Coloca los PNG editados bajo <b>Raiz PNG</b> con rutas relativas coincidentes.</li>
                  <li>Usa <b>Escanear</b>, despues <b>Vista de politica</b> y finalmente <b>Iniciar</b>.</li>
                </ol>
                <h4>Prueba de escalado NCNN directo</h4>
                <ol>
                  <li>Configura el ejecutable NCNN y la carpeta de modelos.</li>
                  <li>Empieza solo con contenido de color/UI/emisivo, o crea reglas de ruta exacta para los archivos que quieres probar.</li>
                  <li>Usa un tile moderado si la VRAM es limitada. Si el backend falla, baja el tile antes de cambiar modelos.</li>
                  <li>Revisa en Comparar y solo despues amplia el filtro.</li>
                </ol>
                <h4>Usar perfiles en una carpeta mixta</h4>
                <ol>
                  <li>Crea o duplica perfiles para color visible, mapas tecnicos de solo preservacion y necesidades especiales de salida DDS.</li>
                  <li>Agrega reglas glob amplias para familias de sufijos comunes cerca de la parte superior.</li>
                  <li>Usa <b>Archivos coincidentes</b> para crear reglas de ruta exacta para excepciones cerca de la parte inferior.</li>
                  <li>Abre <b>Vista de politica</b> y confirma la columna de accion final antes de ejecutar.</li>
                </ol>
                """,
            },
            {
                "id": "compare_review",
                "title": "Comparar y revisar",
                "summary": "Revision lado a lado de DDS original y salida.",
                "keywords": "comparar revisar original salida brillo canales mips",
                "html": """
                <p>Comparar permite revisar la salida antes de confiar en un lote grande.</p>
                <ul>
                  <li>Compara original y resultado visualmente.</li>
                  <li>Busca cambios de brillo, color, alpha, detalles o canales tecnicos.</li>
                  <li>Si algo parece incorrecto, cambia politica, perfil o backend antes de exportar.</li>
                </ul>
                """,
            },
            {
                "id": "archive_browser",
                "title": "Explorador de archivos",
                "summary": "Escaneo, filtro, vista previa, estado activo de mods/originales, Item Finder, extraccion y exportacion desde paquetes.",
                "keywords": "archivo explorador paquete vista previa extraccion parche obj fbx referencias item finder dmm mod activo oculto colocacion hkx",
                "html": """
                <p>El explorador de archivos trabaja sobre paquetes .pamt/.paz. Permite filtrar entradas, previsualizar formatos compatibles, extraer archivos, enviar recursos a investigacion o editor y abrir flujos compatibles de exportacion, importacion y parcheo.</p>
                <ul>
                  <li>La tabla de archivos muestra entradas originales y moddeadas cuando comparten la misma ruta virtual. La columna <b>Estado</b> indica <b>mod activo</b>, <b>original activo</b>, filas ocultas por prioridad o archivos agregados por mod.</li>
                  <li>La vista previa muestra imagenes, texto/XML/HKX con color, resumenes binarios, audio/video, modelos 3D y contexto de materiales/sidecars cuando se puede resolver.</li>
                  <li>La vista previa de modelos intenta resolver geometria, sidecars, texturas, esqueletos y metadatos relacionados.</li>
                  <li><b>Item Finder</b> permite buscar por nombre, categoria, icono y relaciones iteminfo/localizacion; tambien puede iniciar la seleccion de origen de colocacion.</li>
                  <li>Las exportaciones OBJ/FBX pueden escribir un manifiesto con referencias para ayudar al reimportar.</li>
                  <li><b>Importar vista de malla</b> prueba OBJ/DAE/glTF/GLB sin escribir salida.</li>
                  <li><b>Importar malla</b> continua desde la misma revision y puede escribir salida suelta mod-ready o parche compatible despues de confirmar.</li>
                  <li><b>Intercambiar con malla del juego</b> marca una malla del archivo como destino y usa otra malla cargada como origen para el flujo de alineacion.</li>
                  <li><b>Editar HKX</b> y <b>Elegir origen de colocacion</b> copian datos de prefab/socket desde otro arma/modelo. Elige el <code>.pac</code> visible cuando sea posible; el selector muestra una miniatura estatica de geometria y la edicion visual se abre en D3D11 nativo.</li>
                  <li>Los parches directos son compatibles solo para formatos donde la app puede reconstruir datos de forma segura.</li>
                </ul>
                """,
            },
            {
                "id": "texture_editor",
                "title": "Editor de texturas",
                "summary": "Editor por capas para trabajo de texturas visibles.",
                "keywords": "editor texturas capas pintar canales mascara seleccion transformar",
                "html": """
                <p>El editor de texturas esta pensado para trabajos visibles: capas, seleccion, pintura, canales, mascaras, transformaciones y exportacion PNG.</p>
                <p>No convierte automaticamente mapas tecnicos en texturas visibles seguras. Para DDS tecnicos, revisa la semantica y la politica antes de reconstruir.</p>
                """,
            },
            {
                "id": "replace_assistant",
                "title": "Asistente de reemplazo",
                "summary": "Flujo guiado para reemplazos PNG/DDS individuales.",
                "keywords": "asistente reemplazo png dds original salida mod ready",
                "html": """
                <p>El asistente toma una imagen editada, la asocia con el DDS original correcto, reconstruye la salida con la politica actual y prepara una carpeta mod-ready.</p>
                <ul>
                  <li>Usalo cuando ya tengas una textura editada fuera de la app.</li>
                  <li>Comprueba siempre que el archivo original y la salida reconstruida coincidan con la textura esperada.</li>
                </ul>
                """,
            },
            {
                "id": "research",
                "title": "Investigacion",
                "summary": "Revision de familias, clasificacion, referencias, analisis DDS y notas.",
                "keywords": "investigacion familias dds clasificacion referencias notas informes",
                "html": """
                <p>Investigacion agrupa datos para entender familias de texturas y archivos relacionados antes de crear reglas o exportar.</p>
                <ul>
                  <li>Revisa familias DDS y roles inferidos.</li>
                  <li>Clasifica desconocidos y guarda aprobaciones locales.</li>
                  <li>Consulta referencias, restricciones UI, mapas de calor, notas e informes.</li>
                </ul>
                """,
            },
            {
                "id": "text_search",
                "title": "Busqueda de texto",
                "summary": "Busqueda en archivos de texto de archivo o sueltos.",
                "keywords": "busqueda texto xml json cfg lua regex exportar vista previa",
                "html": """
                <p>Busqueda de texto localiza cadenas o patrones regex en archivos de texto de archivo o carpetas sueltas.</p>
                <ul>
                  <li>Previsualiza coincidencias con contexto resaltado.</li>
                  <li>Exporta resultados conservando la estructura de carpetas.</li>
                  <li>Es util para .xml, .json, .cfg, .lua y formatos similares.</li>
                </ul>
                """,
            },
            {
                "id": "settings_files",
                "title": "Configuracion, archivos y dependencias",
                "summary": "Configuracion local, cache, archivos de proyecto y herramientas externas.",
                "keywords": "configuracion archivos cache dependencias texconv ncnn chainner idioma",
                "html": f"""
                <p>La configuracion, el cache y las preferencias se guardan junto a la instalacion o al checkout local.</p>
                <ul>
                  <li><b>Archivo de configuracion</b>: <code>{settings_text}</code></li>
                  <li><b>Cache de archivos</b>: <code>{cache_text}</code></li>
                  <li><b>texconv</b>: fallback legacy opcional. Vista DDS, conversion DDS-a-PNG, comparacion y reconstruccion usan primero DirectXTex/native.</li>
                  <li><b>Real-ESRGAN NCNN</b> y <b>chaiNNer</b>: backends opcionales de escalado.</li>
                  <li><b>Idiomas</b>: puedes exportar el archivo de idioma, editar los valores y volver a importarlo.</li>
                </ul>
                """,
            },
            {
                "id": "troubleshooting",
                "title": "Solucion de problemas y limites",
                "summary": "Errores frecuentes y limitaciones actuales.",
                "keywords": "problemas limites texconv ncnn chainner png brillo cache vista previa",
                "html": """
                <ul>
                  <li><b>Falta texconv</b>: los flujos normales de vista/reconstruccion DDS deben seguir funcionando con DirectXTex/native. Si tambien fallan las herramientas nativas, revisa el empaquetado de herramientas.</li>
                  <li><b>Faltan modelos NCNN</b>: NCNN directo necesita ejecutable y pares .param/.bin validos.</li>
                  <li><b>No hay PNG de salida</b>: si el backend no produce PNG util, no hay nada que reconstruir.</li>
                  <li><b>Rutas chaiNNer incorrectas</b>: una cadena puede leer o escribir en carpetas equivocadas.</li>
                  <li><b>Cambios de brillo o detalle</b>: compara resultados y ajusta modelo, politica o correccion posterior.</li>
                  <li><b>Texturas tecnicas</b>: normales, mascaras, vectores y canales empaquetados deben tratarse con preservacion primero.</li>
                </ul>
                """,
            },
        ]
        sections.extend(
            [
                {
                    "id": "quick_start",
                    "title": "Inicio rapido",
                    "summary": "Ruta inicial para configurar juego, workspace y herramientas.",
                    "keywords": "inicio rapido juego paquete workspace texconv sidecar",
                    "html": """
                    <ol>
                      <li>Crea una carpeta dedicada para la app y coloca alli el .exe portable.</li>
                      <li>En <b>Configuracion &gt; Ubicaciones de archivo</b>, define la ruta del juego/paquete.</li>
                      <li>Ejecuta <b>Inicializar espacio</b> para crear workspace, tools, salida, PNG y extraccion.</li>
                      <li>Usa las herramientas DirectXTex/native incluidas. texconv.exe es solo fallback legacy opcional si quieres configurarlo.</li>
                      <li>Escanea un conjunto pequeno antes de procesar archivos grandes.</li>
                      <li>Para mallas, empieza con <b>Vista previa de importar malla</b> en el Explorador de archivos. Usa <b>Importar malla</b> o <b>Intercambiar con malla del juego</b> solo despues de revisar la alineacion.</li>
                    </ol>
                    <div class="doc-callout doc-warning"><b>Cache de sidecars:</b> puede tardar mucho, pero mejora referencias relacionadas, texturas conectadas a modelos y sidecars de material. Si lo activas, deja que termine.</div>
                    """,
                },
                {
                    "id": "archive_guides",
                    "title": "Guias del explorador de archivos",
                    "summary": "Como navegar, encontrar conexiones, extraer y enviar archivos a otros flujos.",
                    "keywords": "archivo guia navegar referencias conexiones metadatos extraer material xml",
                    "html": """
                    <table>
                      <tr><th>Objetivo</th><th>Usa</th><th>Notas</th></tr>
                      <tr><td>Encontrar un modelo o item</td><td>Busca por ruta, extension, paquete o nombre en juego.</td><td><b>Nombre exacto de item</b> solo aparece con enlace directo iteminfo/localizacion/hash de modelo. <b>Pista de nombre relacionado</b> marca relaciones inferidas, no identidad probada.</td></tr>
                      <tr><td>Saber que duplicado esta activo</td><td>Lee la columna <b>Estado</b>.</td><td><b>Mod activo</b> es la carga que gana sobre el original. Las filas ocultas por prioridad siguen visibles para inspeccion, pero no son la carga activa.</td></tr>
                      <tr><td>Encontrar texturas relacionadas</td><td>Selecciona un modelo y revisa <b>Archivos referenciados</b>.</td><td>Muestra textura, sidecar, esqueleto, animacion, paquete y estado.</td></tr>
                      <tr><td>Elegir origen de colocacion</td><td>Usa <b>Editar HKX</b> y despues <b>Elegir origen de colocacion</b>, o entra desde <b>Item Finder</b>.</td><td>Elige el <code>.pac</code> visible si existe. HKX aporta contexto, pero la colocacion normalmente se resuelve con prefab/socket alrededor de la familia del modelo.</td></tr>
                      <tr><td>Revisar metadatos</td><td>Abre <b>Detalles</b>.</td><td>Incluye tamano, compresion, cadenas legibles, diagnosticos y advertencias.</td></tr>
                      <tr><td>Editar XML/material</td><td>Usa <b>Editar valores de material</b> cuando haya sidecar reconocido.</td><td>Exporta valores editados como paquete mod-ready.</td></tr>
                    </table>
                    <h4>Duplicados moddeados y filas activas</h4>
                    <ul>
                      <li>Si un paquete original y un mod tienen la misma ruta virtual, el explorador mantiene ambas filas para que puedas inspeccionar lo que existe.</li>
                      <li><b>Mod activo</b> u <b>original activo</b> marca la fila que gana. Las filas ocultas por prioridad no son la carga activa. <b>Agregado por mod</b> significa que no hay contraparte original.</li>
                      <li>Revisa esto antes de extraer o reemplazar para saber si estas mirando datos originales o reemplazos de DMM/mod manager.</li>
                    </ul>
                    <p>Usa filtros amplios primero, despues reduce por paquete, rol, extension, carpeta, tamano o vista previa. Para extracciones grandes, verifica el filtro antes de usar exportacion filtrada.</p>
                    """,
                },
                {
                    "id": "mesh_media_guides",
                    "title": "Guias de malla, 3D y medios",
                    "summary": "Exportar, previsualizar, reemplazar mallas y revisar sidecars.",
                    "keywords": "malla 3d obj fbx gltf dae pac pam material sidecar textura",
                    "html": """
                    <table>
                      <tr><th>Accion</th><th>Uso</th><th>Resultado</th></tr>
                      <tr><td>Exportar OBJ</td><td>Edicion round-trip cuando hay sidecar compatible.</td><td>Escribe geometria y contexto para reimportar.</td></tr>
                      <tr><td>Exportar FBX</td><td>Inspeccion o trabajo en DCC.</td><td>Util para ver; no garantiza reimportacion parcheable.</td></tr>
                      <tr><td>Vista previa de importar malla</td><td>Probar OBJ/DAE/glTF/GLB sin escribir archivos.</td><td>Solo crea vista previa.</td></tr>
                      <tr><td>Vista previa de importar DDS</td><td>Probar una textura DDS en el modelo seleccionado sin escribir archivos.</td><td>Solo crea vista previa del modelo.</td></tr>
                      <tr><td>Importar malla</td><td>Crear reemplazo soportado.</td><td>Permite parche o salida suelta mod-ready donde sea compatible.</td></tr>
                      <tr><td>Intercambiar con malla del juego</td><td>Usar otra malla del archivo como reemplazo del objetivo seleccionado.</td><td>Abre Alineacion de reemplazo de malla y conserva archivos relacionados cuando es compatible.</td></tr>
                      <tr><td>Editar HKX</td><td>Copiar colocacion desde otra familia de arma/modelo.</td><td>Muestra contexto del objetivo, permite elegir origen, compara colocacion y crea paquete suelto de colocacion.</td></tr>
                    </table>
                    <h4>Alineacion de reemplazo de malla</h4>
                    <ul>
                      <li>Es la revision principal para reemplazos estaticos e intercambios de malla del juego: geometria, partes mapeadas, texturas, sidecars, posicion, escala, rotacion y valores de exportacion.</li>
                      <li>Usa <b>Vista previa de importar malla</b> antes de escribir archivos.</li>
                      <li>Usa <b>Importar malla</b> solo despues de revisar compatibilidad, ubicacion y plan de texturas.</li>
                      <li>Las anulaciones avanzadas de ranuras DDS son herramientas de reparacion manual; empieza con las sugerencias.</li>
                    </ul>
                    <h4>Autoridad de material y sidecars</h4>
                    <ul>
                      <li><b>Preservar XML runtime</b> mantiene la estructura PAC XML del objetivo/corpus y permite que capas o mapas de soporte originales influyan en el resultado.</li>
                      <li><b>Autoridad de origen real</b> usa PAC/XML original como ABI runtime, pero bloquea influencia visible/soporte original en wrappers activos del origen.</li>
                      <li><b>Autoridad de material manual</b> parte de Preservar XML runtime y expone controles para reparacion avanzada.</li>
                      <li><b>Usar otra malla original</b> permite elegir otra referencia original para alineacion o contexto de material.</li>
                      <li>Revisa estado de colocacion <b>Guardado / en el cuerpo</b> frente a <b>Sostenido / en mano</b> antes de crear paquetes.</li>
                    </ul>
                    <h4>Intercambio con malla del juego</h4>
                    <ol>
                      <li>Selecciona la malla de archivo que quieres reemplazar y marca ese recurso como destino de intercambio.</li>
                      <li>Elige si se incluyen archivos relacionados como texturas, sidecars, esqueletos o animaciones. Esqueletos y animaciones son explicitos porque rigs o fisica incompatibles pueden romper recursos.</li>
                      <li>Selecciona otra malla cargada del archivo como origen.</li>
                      <li>Revisa la colocacion y el mapeo de texturas en <b>Alineacion de reemplazo de malla</b>.</li>
                      <li>Escribe salida suelta o parchea archivos solo cuando el resultado sea visual y estructuralmente razonable.</li>
                    </ol>
                    <div class="doc-callout doc-warning"><b>Limites de malla:</b> los reemplazos estaticos pueden retargetear geometria y sidecars compatibles, pero no convierten todos los rigs, animaciones, skins o grafos de material complejos a datos nativos del juego.</div>
                    <h4>Colocacion HKX y sockets</h4>
                    <ul>
                      <li><b>Abrir colocacion HKX</b> trata el recurso abierto como el objetivo que cambia. <b>Elegir origen de colocacion</b> busca el arma/modelo fuente del que se copiara la colocacion.</li>
                      <li>Elige un <code>.pac</code> visible como origen cuando sea posible. Puedes buscar en los indices del archivo o usar <b>Item Finder</b> para empezar por nombre, icono o categoria.</li>
                      <li>El selector de origen muestra una miniatura estatica de geometria para confirmar el modelo; la edicion visual se abre en D3D11 nativo.</li>
                      <li><b>Comparar colocacion</b> verifica prefab/socket/HKX resueltos antes de empaquetar. <b>Editar valores de socket</b> aparece cuando el XML recuperado se puede mostrar y escribir de forma segura.</li>
                    </ul>
                    """,
                },
                {
                    "id": "mod_packaging",
                    "title": "Empaquetado mod-ready",
                    "summary": "Salida suelta, manifest.json, .no_encrypt y copias de seguridad.",
                    "keywords": "mod ready paquete salida info json no_encrypt backup",
                    "html": """
                    <p>La salida normal y el paquete mod-ready estan separados para que puedas revisar antes de instalar.</p>
                    <ul>
                      <li><b>Output root</b> contiene resultados DDS normales.</li>
                      <li><b>Exportacion mod-ready</b> crea estructura suelta con manifest.json, metadatos opcionales de manager y opcional .no_encrypt.</li>
                      <li>Los parches de archivo requieren confirmacion y usan backup/restauracion cuando esta disponible.</li>
                    </ul>
                    """,
                },
                {
                    "id": "profile_settings",
                    "title": "Perfil y configuracion",
                    "summary": "Que incluyen perfiles, diagnosticos, preferencias e idiomas.",
                    "keywords": "perfil configuracion exportar importar diagnosticos idioma apariencia inicio rendimiento vista editor reemplazo",
                    "html": """
                    <p><b>Perfil &gt; Exportar perfil</b> guarda la configuracion del flujo y una copia completa de los ajustes de la app: rutas, reglas/perfiles, metadatos de paquete, filtros del explorador, apariencia, idioma, inicio, rendimiento, cache/indexacion, vista 3D, Reemplazador, Editor de texturas, avisos de seguridad y geometria de ventanas.</p>
                    <ul>
                      <li><b>Importar perfil</b> restaura primero el flujo y despues recarga esos ajustes en Configuracion, Reemplazador y Editor de texturas.</li>
                      <li><b>Exportar diagnosticos</b> incluye el mismo perfil, logs, resumen de cache, analisis de chaiNNer, contexto de fallos si existe, README, licencia y avisos de terceros.</li>
                      <li><b>Configuracion / Inicio</b>: carga automatica del archivo, preferencia de cache, ultima pestana y filtros del explorador.</li>
                      <li><b>Configuracion / Rendimiento</b>: perfil de recursos, backend de vista, presupuesto UI, workers, aceleracion nativa, indexacion de sidecars y cache D3D11.</li>
                      <li><b>Configuracion / Apariencia</b>: temas, Espanol/Aleman integrados, idiomas personalizados, fuentes, densidad, colores y valores 3D.</li>
                    </ul>
                    <p>Exportar idioma crea JSON con claves en ingles. Manten las claves sin cambios y edita solo los valores traducidos.</p>
                    """,
                },
                {
                    "id": "window_layout",
                    "title": "Ventana y layout",
                    "summary": "Pestanas separables, geometria guardada y memoria de layout.",
                    "keywords": "ventana layout separar acoplar pestana geometria splitter restaurar",
                    "html": """
                    <p>El menu <b>Ventana</b> permite mover areas pesadas a ventanas separadas sin perder su posicion en la navegacion principal.</p>
                    <ul>
                      <li><b>Separar pestana actual</b> mueve la herramienta actual a una ventana nueva y deja un marcador en su lugar.</li>
                      <li><b>Acoplar herramienta actual</b> y <b>Acoplar todas las herramientas</b> devuelven herramientas separadas a sus grupos originales.</li>
                      <li>La geometria separada se guarda como <code>window/detached/&lt;tool&gt;/geometry</code>; la ventana principal usa <code>window/geometry</code>.</li>
                      <li><b>Configuracion / Layout</b> controla si se recuerdan tamanos de paneles y splitters.</li>
                    </ul>
                    """,
                },
                {
                    "id": "safety",
                    "title": "Modelo de seguridad",
                    "summary": "Preservacion, texturas tecnicas y operaciones con confirmacion.",
                    "keywords": "seguridad preservar tecnicas normales mascaras backup dry run",
                    "html": """
                    <div class="doc-callout doc-danger">No todas las DDS son imagenes visibles. Normales, mascaras, altura, vectores y canales empaquetados pueden romperse si pasan por una ruta PNG generica.</div>
                    <ul>
                      <li>Empieza con politica segura y reglas automaticas activas.</li>
                      <li>Usa <b>Vista de politica</b> antes de lotes grandes.</li>
                      <li>Usa Research para clasificar familias dudosas antes de forzar perfiles agresivos.</li>
                    </ul>
                    """,
                },
                {
                    "id": "faq",
                    "title": "FAQ",
                    "summary": "Respuestas cortas a preguntas frecuentes.",
                    "keywords": "faq texconv sidecar ncnn chainner brillo archivo",
                    "html": """
                    <p><b>Necesito texconv?</b><br/>No para los flujos normales. DirectXTex/native se usa primero; texconv queda como fallback legacy opcional.</p>
                    <p><b>Debo escalar todas las texturas?</b><br/>No. Empieza con color/UI/emisivo; conserva primero normales, mascaras y mapas tecnicos.</p>
                    <p><b>Por que tarda el cache de sidecars?</b><br/>Lee muchos sidecars para crear conexiones globales. Es caro, pero util para referencias relacionadas.</p>
                    <p><b>Cuando usar Asistente de reemplazo?</b><br/>Para una textura editada individual. Usa Flujo de texturas para lotes.</p>
                    """,
                },
            ]
        )
        return title, intro_html, sections
