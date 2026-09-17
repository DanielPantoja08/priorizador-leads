# PRD — Priorizador Diario de Leads

**Proyecto:** Assessment técnico, Analista de IA — Gerencia de IA y Transformación
**Versión:** 1.3 · **Estado:** Aprobado para desarrollo · **Fecha:** septiembre de 2026
**Documentos complementarios:** [TRD.md](./TRD.md) (cómo se construye) · [EDA.md](./EDA.md) (evidencia de los datos, se genera en la Fase A)

> **Nota de versión del puntaje.** Las cifras de puntaje y temperatura de este documento son del puntaje **v1**, con el que se diseñó. La app y el pipeline usan hoy **v3** (cada estado de una señal vale lo que dice el histórico; los leads sin conversación quedan «Sin calificar»). Las cifras vigentes están en el [README](../README.md) y se reproducen con `uv run python -m pipeline validate-scoring`.

**Cambios frente a la versión 1.2**
- La lista diaria incluye todos los leads abiertos. Los que quedan sin cupo se marcan como **prioritarios** si son Caliente o si llevan menos de 24 h sin contacto (HU-04).

**Cambios frente a la versión 1.1 (ajustes según el EDA)**
- La velocidad de contacto separa 3,6 veces, no 3,5: la cifra anterior estaba truncada.
- El AUC de los modelos simples queda en el rango de 0,55 a 0,60 (antes decía 0,56 a 0,60).
- Se documenta el método del 55 % de leads sin contacto en 24 h: las fechas con precisión de día se leen como 00:00.
- HU-02 muestra si el modelo de interés está disponible en el punto de venta del lead.

**Cambios frente a la versión 1.0**
- Se agrega una **fase de EDA previa al desarrollo** que debe confirmar, con un script reproducible, las cifras de este documento (RF-13).
- **Estrategia local primero:** todo se construye y valida en local, incluida la app de Streamlit. El despliegue es una fase posterior (sección 10).
- Se agregan requisitos de versionamiento sin coautoría (RNF-11) y de reproducibilidad con uv y Supabase CLI (RNF-12).
- El conjunto de referencia del extractor lo propone la IA y lo revisa una persona (HU-07).

---

## 1. Resumen

Las comercializadoras del grupo reciben leads por WhatsApp, Meta Ads y el formulario web. Hoy todos caen en una misma bandeja y se atienden por orden de llegada. El producto convierte esos leads crudos en una **lista priorizada de gestión diaria por asesor**. Cada lead de la lista incluye lo que el cliente ya dijo en WhatsApp (modelo, cuota inicial, forma de pago, objeción) y la razón por la que está en esa posición. Cada comercializadora ve únicamente su información.

## 2. Problema

En palabras del gerente comercial:

1. **Se atiende por orden de llegada y no por probabilidad de compra.**
2. **Cuatro de cada diez leads no se tocan en las primeras 24 horas.**
3. **La información de WhatsApp no llega al CRM**, así que el asesor empieza cada llamada de cero.

### 2.1 Lo que confirman los datos entregados

*Cifras confirmadas por el EDA ([EDA.md](./EDA.md), sección 3). Las discrepancias que encontró se corrigieron en la versión 1.2.*

| Hallazgo | Evidencia | Implicación para el producto |
|---|---|---|
| La tasa de cierre base es baja | 9,0 % en el histórico (197 de 2.200) | Cada punto de mejora en el orden de atención tiene valor |
| **La velocidad de contacto es la palanca más fuerte** | Contacto en 1 h: 16,7 % de cierre. A las 120 h: 4,7 % (3,6 veces menos) | La prioridad debe incluir **urgencia**, no solo la calidad del lead |
| Los atributos del lead separan poco | AUC entre 0,55 y 0,60 con modelos simples (regresión logística y puntaje v1) | Hay que ser honesto: el puntaje ordena, no predice con certeza |
| Aun así, los extremos sí se diferencian | Grupo "caliente": 15,8 % de cierre. Grupo "frío": 7,3 % (2,2 veces), estable en validación temporal | La temperatura es útil para decidir a quién llamar primero |
| La lentitud es peor que lo que percibe el gerente | 55 % de los leads actuales no fue contactado en 24 h o nunca (las fechas con precisión de día se leen como 00:00) | La vista diaria debe señalar los leads nuevos sin tocar |
| Hay información valiosa en las conversaciones | 677 conversaciones: cuota inicial, forma de pago, citas, objeciones | Extraerla con IA y mostrarla al asesor |

## 3. Objetivos y métricas

| Objetivo | Métrica | Meta de la prueba |
|---|---|---|
| Ordenar por probabilidad y urgencia | Tasa de cierre del grupo "Caliente" frente a "Frío" en el histórico | Al menos 1,8 veces |
| Contactar a tiempo | % de leads nuevos asignados el mismo día | 100 % de los leads nuevos dentro de la capacidad disponible |
| Dar contexto al asesor | % de leads con conversación que quedan enriquecidos | ≥ 95 % |
| Extracción confiable | Exactitud por campo sobre 40 conversaciones con etiquetas revisadas por una persona | ≥ 85 % en modelo, cuota, forma de pago y cita |
| Decisiones basadas en evidencia | Cifras del PRD y del TRD confirmadas por el EDA | 100 % verificadas o corregidas |
| Operar sin intervención | Local: corrida completa con un solo comando. Despliegue: corridas programadas exitosas | 100 % en ambas fases |
| Aislar la información por empresa | Filas de otra empresa visibles para un usuario | 0 |

**Métricas de negocio a futuro** (fuera del alcance de la prueba): tiempo medio al primer contacto, tasa de cierre por temperatura y cumplimiento de la lista diaria por asesor.

## 4. Usuarios

| Usuario | Necesidad | Qué hace en el producto |
|---|---|---|
| **Asesor comercial** | Saber a quién llamar primero y qué decirle | Consulta "Mis leads de hoy", ordenada, con el resumen de cada cliente |
| **Gerente o coordinador comercial** (por empresa) | Ver la carga del equipo y los leads sin cupo | Consulta el tablero de su empresa: distribución por asesor, temperaturas y alertas |
| **Equipo de IA y Transformación** | Operar y auditar el flujo | Revisa la bitácora de ejecuciones, los problemas de calidad y la evaluación del extractor |

## 5. Alcance

### 5.1 Incluido (alcance mínimo del enunciado)

| ID | Requisito funcional |
|---|---|
| RF-01 | Ingerir automáticamente los cinco archivos fuente, sin intervención manual |
| RF-02 | Normalizar teléfono, fecha, ciudad, canal, estado y modelo (este último contra el catálogo) |
| RF-03 | Registrar cada inconsistencia detectada y la acción tomada |
| RF-04 | Detectar y consolidar leads duplicados **dentro de una misma empresa**, incluidos los que llegaron por canales distintos |
| RF-05 | Extraer con IA, de cada conversación: modelo de interés, cuota inicial, forma de pago, intención, objeción principal, si pidió cita y si pidió cotización |
| RF-06 | Calcular para cada lead abierto un puntaje de prioridad y una temperatura (Caliente, Tibio, Frío), con razones legibles |
| RF-07 | Validar la lógica de puntaje contra el histórico y publicar el resultado |
| RF-08 | Asignar los leads del día a asesores activos del mismo punto de venta, respetando su capacidad diaria |
| RF-09 | Persistir todo en una base de datos relacional con esquema versionado |
| RF-10 | Ejecutar el flujo completo con un solo disparo, programado o manual |
| RF-11 | Publicar una vista web "Mis leads de hoy" y un tablero de gerente |
| RF-12 | Garantizar que ningún usuario vea datos de otra empresa |
| RF-13 | Realizar, antes del desarrollo, un EDA reproducible que sustente las cifras del PRD y del TRD y documente las inconsistencias de los datos |

**Nota sobre RF-10 y RF-11:** en la fase local, el disparo único es un comando y la vista web corre en local. En la fase de despliegue, el disparo se programa en GitHub Actions y la vista se publica en una URL pública, como exige el enunciado.

### 5.2 Fuera de alcance

- Integración real con el CRM (se propone como siguiente paso).
- Ingesta en tiempo real desde WhatsApp o Meta.
- Registro de gestiones desde la app: marcar un lead como llamado o cerrado.
- Entrenar un modelo propio de machine learning, que el enunciado no exige.
- Gestión de inventario y reservas.

## 6. Historias de usuario y criterios de aceptación

**HU-01. Mis leads de hoy.** Como asesor, quiero ver mis leads del día ordenados por prioridad, para llamar primero a los que tienen más probabilidad de compra.
- La lista muestra solo los leads asignados a mí para la fecha de corte.
- Está ordenada por prioridad descendente; en caso de empate, primero el lead más antiguo.
- Cada fila muestra: nombre, teléfono, canal, modelo de interés, temperatura, horas desde el registro y estado.

**HU-02. Contexto del cliente.** Como asesor, quiero ver lo que el cliente dijo en WhatsApp sin leer todo el chat, para no empezar de cero.
- El detalle del lead muestra los campos extraídos, las razones del puntaje y la conversación completa.
- Si el lead no tiene conversación, se indica "Sin conversación" y los campos aparecen como "No informa".
- Si la persona escribió por varios canales, se ven todos sus leads consolidados.
- Se indica si el modelo de interés está disponible en el punto de venta del lead. Es un dato informativo y no cambia el puntaje.

**HU-03. Urgencia visible.** Como asesor, quiero identificar de inmediato los leads nuevos sin contactar, porque son los que más se pierden.
- Los leads sin contacto con menos de 24 h tienen una marca visual.
- Su prioridad incluye un componente de urgencia documentado.

**HU-04. Tablero de gerente.** Como gerente, quiero ver cómo quedó distribuida la carga de mi empresa.
- Muestra los leads asignados por asesor frente a su capacidad, la distribución por temperatura y los leads sin cupo.
- Los leads sin cupo **prioritarios** (Caliente, o sin contacto con menos de 24 h) aparecen primero y resaltados. La marca no cambia la asignación automática; el gerente decide si los reasigna.
- Muestra únicamente datos de la empresa del usuario.

**HU-05. Aislamiento.** Como comercializadora, quiero que otra empresa del grupo nunca vea mis clientes.
- Un usuario de EMP-01 no puede consultar filas de EMP-02 ni de EMP-03, ni desde la app ni con consultas directas usando su sesión.
- Una persona que existe en dos empresas aparece como dos clientes independientes.

**HU-06. Operación desatendida.** Como equipo de IA, quiero que el flujo corra solo y deje trazabilidad.
- En local, un solo comando ejecuta todas las etapas. En despliegue, un workflow programado ejecuta ese mismo comando.
- Cada corrida registra su estado, las filas procesadas por etapa, las llamadas al LLM y los errores.
- Si el LLM no está disponible, el flujo termina usando el extractor por reglas y registra ese hecho.

**HU-07. Confianza en la IA.** Como evaluador, quiero ver qué tan bien extrae la IA.
- Existe un conjunto de 40 conversaciones cuyas etiquetas propuso la IA y **revisó y corrigió una persona**. La documentación lo declara así.
- La evaluación usa solo registros revisados.
- Se reporta la exactitud por campo del extractor con LLM y del extractor por reglas.

**HU-08. Evidencia de las cifras.** Como evaluador, quiero comprobar que los números que justifican el diseño salen de los datos.
- `docs/EDA.md` se genera con un comando y siempre produce el mismo resultado.
- Incluye una tabla que compara cada cifra del PRD y del TRD con el valor calculado.
- Las diferencias se reportan con su causa; no se ajusta el análisis para que coincida.

## 7. Requisitos no funcionales

| ID | Requisito |
|---|---|
| RNF-01 | **Seguridad:** ninguna credencial en el repositorio, incluidas las llaves locales de Supabase. Los secretos viven en `.env` y `.streamlit/secrets.toml` (ignorados por git) en local, y en GitHub Secrets y `st.secrets` en despliegue |
| RNF-02 | **Aislamiento:** la separación por empresa se aplica en la base de datos (Row Level Security), no solo en la interfaz |
| RNF-03 | **Idempotencia:** ejecutar el flujo varias veces con los mismos insumos produce el mismo resultado, sin duplicados |
| RNF-04 | **Explicabilidad:** todo puntaje incluye las razones que lo componen |
| RNF-05 | **Costo:** el componente de IA opera dentro del tier gratuito del proveedor, usando lotes y caché |
| RNF-06 | **Resiliencia:** si falla el LLM, el flujo recurre al extractor por reglas y no se detiene |
| RNF-07 | **Tiempo de ejecución:** una corrida sin conversaciones nuevas termina en menos de 5 minutos |
| RNF-08 | **Trazabilidad:** cada extracción guarda el extractor usado, el modelo y la versión del prompt |
| RNF-09 | **Disponibilidad:** en la fase de despliegue, la URL pública debe funcionar el día de la sustentación |
| RNF-10 | **Mantenibilidad:** código modular con pruebas; las pruebas no dependen de servicios externos |
| RNF-11 | **Versionamiento:** commits pequeños y frecuentes con Conventional Commits, **sin coautoría ni atribución de herramientas**; el único autor es el desarrollador. Se documenta en `CLAUDE.md` |
| RNF-12 | **Reproducibilidad:** entorno de Python gestionado con uv (`uv.lock` versionado) y base de datos local con Supabase CLI. La solución completa se reconstruye desde cero con pocos comandos documentados |

## 8. Supuestos

Los supuestos 1 a 6 se enviaron como preguntas al contacto de la convocatoria y se actualizarán según su respuesta. Los supuestos 7 y 8 son decisiones propias del proyecto.

1. Las tres empresas de los datos (EMP-01 Antioquia, EMP-02 Costa Atlántica, EMP-03 Bogotá y Soacha) son las comercializadoras del grupo, con cinco puntos de venta cada una.
2. Los duplicados solo se consolidan dentro de una misma empresa.
3. La fecha de corte es configurable; por defecto es la última fecha con registros (10 de septiembre de 2026).
4. La lista diaria incluye todos los leads abiertos. Se excluyen los descartados.
5. Los datos son sintéticos y pueden incluirse en el repositorio.
6. El acceso a la app es con usuarios de demostración por empresa.
7. El punto de venta del lead es el correcto para asignarlo. La ciudad declarada por el cliente puede no coincidir con la del punto de venta, y eso no se considera un error.
8. El desarrollo y la validación se hacen en local, con Docker, Supabase CLI y uv disponibles en la máquina del desarrollador. El despliegue se hace después, sin cambios de código.

## 9. Riesgos

| Riesgo | Mitigación |
|---|---|
| Se agota la cuota gratuita del LLM | Lotes, caché por hash y extractor por reglas como respaldo |
| Poder predictivo bajo del histórico | Comunicarlo con transparencia; combinar calidad con urgencia |
| Señales conversacionales sin validación histórica | Pesos pequeños, marcados como heurísticos, y un plan de validación futura |
| Fechas ambiguas (dd/mm frente a mm/dd) | Regla de resolución documentada y registro de cada caso |
| La URL se duerme o el proyecto de Supabase se pausa | El cron diario mantiene la actividad; verificación el día anterior a la demo |
| Fuga de datos entre empresas | RLS, vistas con `security_invoker`, y una prueba automática de aislamiento |
| El EDA contradice cifras del diseño | Punto de control después del EDA; los documentos se corrigen antes de programar |
| Diferencias entre el entorno local y el remoto | Mismo motor (Supabase), mismas migraciones, solo cambian los secretos; verificación completa tras desplegar |
| Poco tiempo para desplegar al final | Reservar el último tramo del plazo para el despliegue y no iniciarlo sin la fase local cerrada |
| La herramienta de desarrollo agrega coautoría a los commits | Ajuste de atribución, regla en `CLAUDE.md`, hook `commit-msg` y verificación del historial |
| Docker o Supabase CLI no disponibles | Verificarlos antes de empezar la Fase A |

## 10. Estrategia de entrega y cronograma

La solución se construye **local primero**: base de datos con Supabase CLI, pipeline con uv y app de Streamlit en la máquina del desarrollador. Solo cuando la fase local está validada (TRD, sección 16.1) se despliega. Cada fase termina en un punto de control con revisión humana.

| Día | Fase | Entrega |
|---|---|---|
| 1 | A | Repositorio (uv, Supabase CLI, hook de commits, `CLAUDE.md`) y **EDA** con la verificación de cifras. Correcciones al PRD y TRD si hacen falta |
| 1–2 | B | Migraciones, RLS, usuarios de demostración, ingesta, normalización y deduplicación |
| 2–3 | C | Extractor por reglas y con Gemini, conjunto de referencia revisado, evaluación |
| 3 | D | Puntaje validado, asignación y CLI completa |
| 4 | E | App de Streamlit local, prueba de aislamiento, README. **Cierre de la fase local** |
| 4–5 | F | Despliegue: Supabase remoto, GitHub Actions, Streamlit Community Cloud, verificación de la URL |
| 5 | — | Diagrama de arquitectura, presentación de 8 diapositivas, ensayo de la demo sobre la URL pública |

**Entregables finales** (los que exige el enunciado): enlace al repositorio, URL pública, README, diagrama de arquitectura y presentación. Adicionalmente: `docs/EDA.md`, `docs/PRD.md`, `docs/TRD.md` y `CLAUDE.md`.

## 11. Siguientes pasos (con más tiempo)

- Integración bidireccional con el CRM para registrar gestiones y cerrar el ciclo de aprendizaje.
- Recalibrar los pesos con los desenlaces reales de los leads priorizados, incluidas las señales conversacionales.
- Disparo por evento: procesar cada lead y cada conversación al llegar, en lugar de una vez al día.
- Notificación al asesor por WhatsApp o correo cuando entra un lead caliente.
- Reasignación durante el día si un asesor no gestiona sus leads a tiempo.
