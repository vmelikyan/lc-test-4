#!/usr/bin/env python3
"""Capture read-only, allowlisted Kubernetes and HTTP evidence for an environment."""

import argparse
import copy
import datetime
import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

VERSION = 1
RESTART_ANNOTATION = "kubectl.kubernetes.io/restartedAt"
REVISION_ANNOTATION = "deployment.kubernetes.io/revision"
STABLE_KINDS = {"Deployment", "Service", "Ingress", "CronJob", "HorizontalPodAutoscaler"}
LIST_KINDS = ("services", "ingresses", "jobs", "cronjobs", "persistentvolumeclaims", "pods", "horizontalpodautoscalers")


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def pick(value, keys):
    return {key: value[key] for key in keys if key in value}


def identity(obj):
    return pick(obj.get("metadata", {}), ("name", "namespace", "uid", "generation", "deletionTimestamp"))


def config_hash(obj, ignore_restart):
    # Exclude server bookkeeping and status. Preserve all spec, labels and
    # annotations, including env values, in the digest, never in the output.
    meta = obj.get("metadata", {})
    config = copy.deepcopy({"labels": meta.get("labels", {}),
                            "annotations": meta.get("annotations", {}),
                            "spec": obj.get("spec", {})})
    if obj.get("kind") == "Deployment":
        config["annotations"].pop(REVISION_ANNOTATION, None)
    if ignore_restart:
        def normalize(value):
            if not isinstance(value, dict):
                return
            annotations = value.get("annotations")
            if isinstance(annotations, dict):
                annotations.pop(RESTART_ANNOTATION, None)
                if not annotations:
                    value.pop("annotations")
            for key, child in value.items():
                if key in ("metadata", "spec", "template", "jobTemplate"):
                    normalize(child)
        normalize(config)
    return digest(config)


def command_summary(container, key):
    # Shell arguments can embed credentials. Never print them verbatim.
    value = container.get(key)
    return {"present": value is not None, "count": len(value or []), "sha256": digest(value)}


def pod_summary(spec):
    volumes = []
    for volume in spec.get("volumes", []):
        row = {"name": volume.get("name"), "types": sorted(k for k in volume if k != "name")}
        for source, keys in (("persistentVolumeClaim", ("claimName", "readOnly")),
                             ("configMap", ("name",)), ("secret", ("secretName",)),
                             ("emptyDir", ("medium", "sizeLimit"))):
            if source in volume:
                row[source] = pick(volume[source], keys)
        volumes.append(row)
    containers = []
    for category in ("initContainers", "containers", "ephemeralContainers"):
        for container in spec.get(category, []):
            containers.append({"category": category,
                               **pick(container, ("name", "image", "workingDir", "restartPolicy")),
                               "command": command_summary(container, "command"),
                               "args": command_summary(container, "args"),
                               "ports": [pick(port, ("name", "containerPort", "protocol"))
                                         for port in container.get("ports", [])],
                               "volumeMounts": [pick(mount, ("name", "mountPath", "subPath", "readOnly"))
                                                for mount in container.get("volumeMounts", [])]})
    return {"serviceAccountName": spec.get("serviceAccountName", "default"),
            "restartPolicy": spec.get("restartPolicy"), "containers": containers, "volumes": volumes,
            "pvcNames": sorted({v["persistentVolumeClaim"]["claimName"] for v in volumes
                                if "persistentVolumeClaim" in v})}


def summarize(obj, ignore_restart):
    kind, spec, status = obj["kind"], obj.get("spec", {}), obj.get("status", {})
    row = {"kind": kind, **identity(obj), "configurationSha256": config_hash(obj, ignore_restart),
           "ownerReferences": [pick(owner, ("apiVersion", "kind", "name", "uid", "controller"))
                               for owner in obj.get("metadata", {}).get("ownerReferences", [])]}
    if kind in ("Deployment", "Job"):
        row["podTemplate"] = pod_summary(spec.get("template", {}).get("spec", {}))
    if kind == "Deployment":
        revision = obj.get("metadata", {}).get("annotations", {}).get(REVISION_ANNOTATION)
        row["controllerRevision"] = revision if isinstance(revision, str) and revision.isdecimal() else None
        row["replicas"] = spec.get("replicas", 1)
        row["readiness"] = {key: status.get(key, 0) for key in
                            ("replicas", "updatedReplicas", "readyReplicas", "availableReplicas", "observedGeneration")}
    elif kind == "Pod":
        row["pod"] = pod_summary(spec)
        row["phase"] = status.get("phase")
        row["ready"] = any(c.get("type") == "Ready" and c.get("status") == "True"
                           for c in status.get("conditions", []))
        row["containerStatus"] = []
        for category in ("initContainerStatuses", "containerStatuses", "ephemeralContainerStatuses"):
            for container in status.get(category, []):
                state = container.get("state", {})
                row["containerStatus"].append({"category": category,
                    **pick(container, ("name", "ready", "restartCount", "imageID", "containerID")),
                    "state": {key: pick(value, ("reason", "exitCode", "signal", "startedAt", "finishedAt"))
                              for key, value in state.items()}})
    elif kind == "Service":
        row.update(pick(spec, ("type", "clusterIP", "clusterIPs")))
        row["ports"] = [pick(port, ("name", "port", "targetPort", "protocol", "nodePort"))
                        for port in spec.get("ports", [])]
    elif kind == "Ingress":
        row["hosts"] = sorted({rule["host"] for rule in spec.get("rules", []) if "host" in rule})
        row["ingressClassName"] = spec.get("ingressClassName")
    elif kind == "Job":
        row.update({key: status.get(key, 0) for key in ("active", "succeeded", "failed")})
        row["conditions"] = [pick(condition, ("type", "status", "reason"))
                             for condition in status.get("conditions", [])]
    elif kind == "CronJob":
        row.update({"schedule": spec.get("schedule"), "suspend": spec.get("suspend", False)})
        row["podTemplate"] = pod_summary(spec.get("jobTemplate", {}).get("spec", {}).get("template", {}).get("spec", {}))
        row["activeJobs"] = [pick(job, ("name", "namespace", "uid")) for job in status.get("active", [])]
    elif kind == "HorizontalPodAutoscaler":
        row.update(pick(spec, ("minReplicas", "maxReplicas", "scaleTargetRef")))
        row["scalingStatus"] = pick(status, ("currentReplicas", "desiredReplicas", "lastScaleTime"))
    elif kind in ("PersistentVolumeClaim", "PersistentVolume"):
        row.update(pick(spec, ("storageClassName", "volumeName", "volumeMode", "accessModes", "persistentVolumeReclaimPolicy", "capacity")))
        row["phase"] = status.get("phase")
        if "claimRef" in spec:
            row["claimRef"] = pick(spec["claimRef"], ("namespace", "name", "uid"))
        if "csi" in spec:
            row["csiDriver"] = spec["csi"].get("driver")
    return row


def error_kind(stderr):
    # Do not retain raw kubectl errors: they may contain URLs or credential data.
    for token, category in (("Forbidden", "forbidden"), ("Unauthorized", "unauthorized"),
                            ("NotFound", "not_found_error"), ("timed out", "timeout"),
                            ("deadline exceeded", "timeout"), ("connection refused", "unreachable")):
        if token in stderr:
            return category
    return "kubectl_failed"


class Observer:
    def __init__(self, args, result):
        self.args, self.result = args, result

    def get(self, resource, name=None, namespaced=True):
        query = {"resource": resource, "name": name, "namespace": self.args.namespace if namespaced else None}
        command = ["kubectl", "--context", self.args.context,
                   "--request-timeout=" + str(self.args.timeout) + "s"]
        if namespaced:
            command += ["--namespace", self.args.namespace]
        command += ["get", resource]
        if name:
            command += [name, "--ignore-not-found"]
        command += ["--output", "json"]
        try:
            process = subprocess.run(command, capture_output=True, text=True, timeout=self.args.timeout + 2, check=False)
            if process.returncode:
                self.result["queries"].append({**query, "state": "error", "exitCode": process.returncode,
                                               "error": error_kind(process.stderr)})
                return None
            if name and not process.stdout.strip():
                self.result["queries"].append({**query, "state": "absent"})
                return None
            obj = json.loads(process.stdout)
            if not isinstance(obj, dict) or (not name and not isinstance(obj.get("items"), list)):
                raise ValueError("Invalid resource response")
            if name and (not obj.get("kind") or obj.get("metadata", {}).get("name") != name):
                raise ValueError("Resource identity mismatch")
            self.result["queries"].append({**query, "state": "present", "count": 1 if name else len(obj["items"])})
            return obj
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            self.result["queries"].append({**query, "state": "error", "error": type(error).__name__})
            return None


def _http_probe(url, marker, timeout, expected_status):
    target = urlsplit(url)
    connection_type = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
    connection = connection_type(target.hostname, target.port, timeout=timeout)
    row = {"url": url, "expectedStatus": expected_status, "expectedMarker": marker}
    try:
        connection.request("GET", target.path or "/")
        response = connection.getresponse()
        body = response.read(65537)
        row.update(status=response.status, markerFound=marker.encode("utf-8") in body[:65536],
                   bodyTruncated=len(body) > 65536, redirectsFollowed=False)
        row["pass"] = row["status"] == expected_status and row["markerFound"] and not row["bodyTruncated"]
    except (OSError, http.client.HTTPException) as error:
        row.update(error=type(error).__name__, **{"pass": False})
    finally:
        connection.close()
    return row


def http_check(url, marker, timeout, expected_status):
    # Bound DNS, connection and the complete response read together. A socket
    # inactivity timeout alone permits an arbitrarily long slow-drip response.
    worker = ("import json,runpy,sys; module=runpy.run_path(sys.argv[1]); "
              "print(json.dumps(module['_http_probe'](sys.argv[2],sys.argv[3],int(sys.argv[4]),int(sys.argv[5]))))")
    row = {"url": url, "expectedStatus": expected_status, "expectedMarker": marker,
           "deadlineSeconds": timeout}
    try:
        process = subprocess.run([sys.executable, "-c", worker, str(Path(__file__).resolve()),
                                  url, marker, str(timeout), str(expected_status)],
                                 capture_output=True, text=True, timeout=timeout, check=False)
        if process.returncode:
            return {**row, "error": "probe_worker_failed", "pass": False}
        return {**row, **json.loads(process.stdout)}
    except subprocess.TimeoutExpired:
        return {**row, "error": "probe_deadline_exceeded", "pass": False}
    except (OSError, ValueError):
        return {**row, "error": "probe_worker_failed", "pass": False}


def indexed(rows):
    return {(row["kind"], row.get("namespace", ""), row["name"]): row for row in rows}


def compare(before, current):
    old, new = indexed(before), indexed(current)
    changes = []
    for key in sorted(old.keys() | new.keys()):
        fields = ["presence"] if key not in old or key not in new else [
            field for field in ("uid", "configurationSha256") if old[key].get(field) != new[key].get(field)]
        if fields:
            changes.append({"kind": key[0], "namespace": key[1], "name": key[2],
                            "state": "added" if key not in old else "removed" if key not in new else "changed",
                            "fields": fields})
    return changes


def collect(args, result):
    baseline = None
    if args.baseline:
        try:
            with args.baseline.open() as handle:
                baseline = json.load(handle)
            valid = (baseline["schemaVersion"] == VERSION and baseline["target"] == result["target"]
                     and baseline["normalization"] == result["normalization"] and baseline["pass"])
            result["checks"]["baselineCompatible"] = bool(valid)
            if not valid:
                return
        except (OSError, ValueError, KeyError, TypeError):
            result["checks"]["baselineCompatible"] = False
            return
    observer = Observer(args, result)
    namespace = observer.get("namespace", args.namespace, namespaced=False)
    result["namespace"] = summarize(namespace, args.ignore_restarted_at) if namespace else None
    if namespace:
        deployment = observer.get("deployment", args.deployment)
        if deployment:
            result["resources"].append(summarize(deployment, args.ignore_restarted_at))
        for resource in LIST_KINDS:
            response = observer.get(resource)
            for obj in response.get("items", []) if response else []:
                result["resources"].append(summarize(obj, args.ignore_restarted_at))
        closing_namespace = observer.get("namespace", args.namespace, namespaced=False)
        result["checks"]["namespaceStableDuringCapture"] = bool(
            closing_namespace and identity(closing_namespace).get("uid") == identity(namespace).get("uid"))
    referenced_volumes = {row["volumeName"] for row in result["resources"]
                          if row["kind"] == "PersistentVolumeClaim" and row.get("volumeName")}
    volume_names = set(referenced_volumes)
    if baseline:
        volume_names.update(row["name"] for row in baseline["resources"] if row["kind"] == "PersistentVolume")
    result["trackedVolumeNames"] = sorted(volume_names)
    for name in sorted(volume_names):
        volume = observer.get("persistentvolume", name, namespaced=False)
        if volume:
            result["resources"].append(summarize(volume, args.ignore_restarted_at))
    if referenced_volumes:
        observed_volumes = {row["name"] for row in result["resources"] if row["kind"] == "PersistentVolume"}
        result["checks"]["referencedVolumesPresent"] = referenced_volumes <= observed_volumes
    result["resources"].sort(key=lambda row: (row["kind"], row["name"]))
    selected = next((row for row in result["resources"] if row["kind"] == "Deployment"), None)
    if args.expect_absent:
        result["checks"]["namespaceAbsent"] = namespace is None
        result["checks"]["trackedVolumesAbsent"] = not any(row["kind"] == "PersistentVolume" for row in result["resources"])
    else:
        result["checks"]["namespacePresent"] = namespace is not None and not namespace.get("metadata", {}).get("deletionTimestamp")
        result["checks"]["deploymentPresent"] = selected is not None and not selected.get("deletionTimestamp")
        if args.require_ready:
            ready = selected.get("readiness", {}) if selected else {}
            replicas = selected.get("replicas", 0) if selected else 0
            result["checks"]["deploymentReady"] = bool(selected and replicas > 0
                and ready.get("observedGeneration", 0) >= selected.get("generation", 0)
                and ready.get("replicas", 0) == replicas and ready.get("updatedReplicas", 0) == replicas
                and ready.get("readyReplicas", 0) >= replicas and ready.get("availableReplicas", 0) >= replicas)
        if args.require_pvc:
            result["checks"]["selectedPvcAttachedAndBound"] = bool(selected
                and args.require_pvc in selected["podTemplate"]["pvcNames"]
                and any(row["kind"] == "PersistentVolumeClaim" and row["name"] == args.require_pvc
                        and row["phase"] == "Bound" for row in result["resources"]))
        if args.expect_no_pvc:
            result["checks"]["selectedDeploymentHasNoPvc"] = bool(selected and not selected["podTemplate"]["pvcNames"])
    if baseline:
        result["comparison"] = compare(baseline["resources"], result["resources"])
        if args.verify != "diff":
            result["checks"]["sameNamespaceUid"] = bool(result["namespace"] and baseline["namespace"]
                and result["namespace"]["uid"] == baseline["namespace"]["uid"])
            before = [row for row in baseline["resources"] if row["kind"] in STABLE_KINDS]
            current = [row for row in result["resources"] if row["kind"] in STABLE_KINDS]
            stable_changes = compare(before, current)
            result["checks"]["stableResourceIdentities"] = not any(
                change["state"] == "removed" or "uid" in change["fields"] for change in stable_changes)
            if args.verify == "restored":
                result["checks"]["stableResourceConfigurationsRestored"] = not stable_changes
    for url, marker in args.http:
        result["http"].append(http_check(url, marker, args.timeout, args.expected_status))
    if args.http:
        result["checks"]["httpPassed"] = all(row["pass"] for row in result["http"])


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("context", "namespace", "deployment"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--output", required=True, type=Path, help="New JSON evidence file. Existing files are never overwritten.")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--verify", choices=("diff", "identity", "restored"), default="diff")
    parser.add_argument("--ignore-restarted-at", action="store_true", help="Remove only the rollout restart annotation from config hashes.")
    parser.add_argument("--require-ready", action="store_true")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--require-pvc", metavar="NAME")
    group.add_argument("--expect-no-pvc", action="store_true")
    parser.add_argument("--expect-absent", action="store_true")
    parser.add_argument("--http", nargs=2, action="append", default=[], metavar=("URL", "MARKER"))
    parser.add_argument("--expected-status", type=int, default=200)
    parser.add_argument("--timeout", type=int, default=10, help="Per-request timeout in seconds, from 1 to 60.")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 60 or not 100 <= args.expected_status <= 599:
        parser.error("Use a timeout from 1 to 60 and an HTTP status from 100 to 599.")
    if args.verify != "diff" and not args.baseline:
        parser.error("--verify identity/restored requires --baseline.")
    if args.expect_absent and (args.http or args.require_ready or args.require_pvc or args.expect_no_pvc or args.verify != "diff"):
        parser.error("--expect-absent cannot be combined with presence checks.")
    for value in (args.context, args.namespace, args.deployment, args.require_pvc):
        if value is not None and (not value or value.startswith("-") or any(char.isspace() for char in value)):
            parser.error("Resource and context names must be nonempty and cannot start with '-' or contain whitespace.")
    for url, marker in args.http:
        try:
            parsed = urlsplit(url)
            valid = (parsed.scheme in ("http", "https") and parsed.hostname and parsed.port != 0
                     and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment)
        except ValueError:
            valid = False
        if not valid or not marker or len(marker) > 256:
            parser.error("Use an HTTP(S) URL without credentials, query or fragment, and a nonsecret marker of 1–256 characters.")
    return args


def main():
    args = arguments()
    result = {"schemaVersion": VERSION, "startedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "target": {"context": args.context, "namespace": args.namespace, "deployment": args.deployment},
              "normalization": {"hashAlgorithm": "sha256-canonical-json", "configurationFields": ["metadata.labels", "metadata.annotations", "spec"],
                                "ignoredAnnotation": RESTART_ANNOTATION if args.ignore_restarted_at else None,
                                "excludedControllerBookkeeping": {"Deployment": ["metadata.annotations." + REVISION_ANNOTATION]},
                                "commands": "hashes-only"},
              "verify": args.verify, "namespace": None, "resources": [], "queries": [], "checks": {}, "http": []}
    # Reserve output first so a failed read still has an evidence destination.
    try:
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        print("Cannot create output. Use a new file in an existing writable directory.", file=sys.stderr)
        return 2
    with os.fdopen(descriptor, "w") as handle:
        try:
            collect(args, result)
        except Exception as error:
            result["captureError"] = type(error).__name__
            result["checks"]["captureCompleted"] = False
        result["checks"]["allKubernetesReadsSucceeded"] = bool(result["queries"]) and all(
            query["state"] != "error" for query in result["queries"])
        result["pass"] = bool(result["checks"]) and all(result["checks"].values())
        result["finishedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        json.dump(result, handle, indent=2)
        handle.write("\n")
    print(json.dumps({"output": str(args.output), "pass": result["pass"], "checks": result["checks"]}))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
