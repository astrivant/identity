{{/* Select only workers from this release revision; old completed Jobs must not affect placement. */}}
{{- define "witful.workerSelector" -}}
app.kubernetes.io/name: witful
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: sync
witful.io/job-revision: {{ .Release.Revision | quote }}
{{- end -}}

{{/* Refuse conflicting controls instead of silently dropping an operator's scheduling rules. */}}
{{- define "witful.validatePlacement" -}}
{{- if and .Values.scheduling.affinity .Values.scheduling.podAntiAffinityPreset -}}
{{- fail "set scheduling.affinity or scheduling.podAntiAffinityPreset, not both" -}}
{{- end -}}
{{- range $key, $value := .Values.podLabels -}}
{{- if hasKey (include "witful.workerSelector" $ | fromYaml) $key -}}
{{- fail (printf "podLabels cannot override reserved label %s" $key) -}}
{{- end -}}
{{- end -}}
{{- end -}}
