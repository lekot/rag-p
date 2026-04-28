{{- define "rag-p-runtime.labels" -}}
app.kubernetes.io/name: rag-p-runtime
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
{{- end }}

{{- define "rag-p-runtime.ollamaSelectorLabels" -}}
app.kubernetes.io/name: {{ .Values.ollama.name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: ollama
{{- end }}

{{- define "rag-p-runtime.ollamaLabels" -}}
{{ include "rag-p-runtime.labels" . }}
{{ include "rag-p-runtime.ollamaSelectorLabels" . }}
{{- end }}
