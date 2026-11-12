{{/*
knowledge-mcp: метки и имя сервиса. Опираются на стандартные хелперы чарта
<chart>.fullname / <chart>.labels / <chart>.selectorLabels из _helpers.tpl.
*/}}
{{- define "<chart>.knowledgeMcp.labels" -}}
{{ include "<chart>.labels" . }}
app.kubernetes.io/component: knowledge-mcp
{{- end }}

{{- define "<chart>.knowledgeMcp.selectorLabels" -}}
{{ include "<chart>.selectorLabels" . }}
app.kubernetes.io/component: knowledge-mcp
{{- end }}

{{- define "<chart>.knowledgeMcp.serviceName" -}}
{{- printf "%s-knowledge-mcp" (include "<chart>.fullname" .) }}
{{- end }}
