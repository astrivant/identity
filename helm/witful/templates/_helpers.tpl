{{/* Select only workers from this release revision; old completed Jobs must not affect placement. */}}
{{- define "witful.workerSelector" -}}
app.kubernetes.io/name: witful
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: sync
witful.io/job-revision: {{ .Release.Revision | quote }}
{{- end -}}

{{/* Refuse conflicting controls instead of silently dropping an operator's scheduling rules. */}}
{{- define "witful.validatePlacement" -}}
{{- if and .settings.scheduling.affinity .settings.scheduling.podAntiAffinityPreset -}}
{{- fail (printf "set %s.scheduling.affinity or %s.scheduling.podAntiAffinityPreset, not both" .path .path) -}}
{{- end -}}
{{- range $key, $value := .settings.podLabels -}}
{{- if hasKey (include "witful.workerSelector" $.root | fromYaml) $key -}}
{{- fail (printf "%s.podLabels cannot override reserved label %s" $.path $key) -}}
{{- end -}}
{{- end -}}
{{- end -}}
