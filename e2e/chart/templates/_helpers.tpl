{{- define "e2e.labels" -}}
app.kubernetes.io/name: lifecycle-release-check
app.kubernetes.io/instance: {{ .Release.Name | quote }}
app.kubernetes.io/part-of: lifecycle-release-e2e
lc-service: {{ .Values.serviceName | quote }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{- define "e2e.podSecurity" -}}
automountServiceAccountToken: false
serviceAccountName: lifecycle-workload
restartPolicy: Never
terminationGracePeriodSeconds: 5
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  runAsGroup: 10001
  seccompProfile:
    type: RuntimeDefault
{{- end }}
