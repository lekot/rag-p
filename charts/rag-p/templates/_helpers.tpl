{{/*
Expand the name of the chart.
*/}}
{{- define "rag-p.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "rag-p.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart label.
*/}}
{{- define "rag-p.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels.
*/}}
{{- define "rag-p.labels" -}}
helm.sh/chart: {{ include "rag-p.chart" . }}
{{ include "rag-p.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels.
*/}}
{{- define "rag-p.selectorLabels" -}}
app.kubernetes.io/name: {{ include "rag-p.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Component-specific selector labels.
Usage: include "rag-p.componentSelectorLabels" (dict "root" . "component" "api")
*/}}
{{- define "rag-p.componentSelectorLabels" -}}
app.kubernetes.io/name: {{ include "rag-p.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
Component labels (includes common labels + component).
Usage: include "rag-p.componentLabels" (dict "root" . "component" "api")
*/}}
{{- define "rag-p.componentLabels" -}}
helm.sh/chart: {{ include "rag-p.chart" .root }}
{{ include "rag-p.componentSelectorLabels" . }}
{{- if .root.Chart.AppVersion }}
app.kubernetes.io/version: {{ .root.Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
{{- end }}

{{/*
Full image reference with optional global registry override.
Usage: include "rag-p.image" (dict "root" . "image" .Values.api.image)
*/}}
{{- define "rag-p.image" -}}
{{- $registry := .image.registry | default .root.Values.global.imageRegistry | default "" }}
{{- $repo := .image.repository }}
{{- $tag := .image.tag | default "latest" }}
{{- if $registry }}
{{- printf "%s/%s:%s" $registry $repo $tag }}
{{- else }}
{{- printf "%s:%s" $repo $tag }}
{{- end }}
{{- end }}

{{/*
Service account name.
*/}}
{{- define "rag-p.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "rag-p.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Postgres DSN built from CNPG secret convention.
*/}}
{{- define "rag-p.postgresDSN" -}}
postgresql://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@{{ include "rag-p.fullname" . }}-postgres-rw:5432/{{ .Values.postgres.cnpg.databaseName }}
{{- end }}

{{/*
Redis URL from bitnami redis chart convention.
*/}}
{{- define "rag-p.redisURL" -}}
{{- if .Values.redis.auth.enabled }}
redis://:$(REDIS_PASSWORD)@{{ .Release.Name }}-redis-master:6379/0
{{- else }}
redis://{{ .Release.Name }}-redis-master:6379/0
{{- end }}
{{- end }}
