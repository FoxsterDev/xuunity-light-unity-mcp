using System;
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;
using XUUnity.LightMcp.Editor.Core;

namespace XUUnity.LightMcp.Editor.Helpers
{
    internal sealed class XUUnityLightMcpPrefabLoadResult
    {
        public GameObject Root;
        public string NormalizedPath = "";
        public string Guid = "";
        public XUUnityLightMcpUiDiagnostic Error;
    }

    internal static class XUUnityLightMcpPrefabInspector
    {
        const int MAX_PROPERTIES_PER_COMPONENT = 512;

        public static XUUnityLightMcpPrefabLoadResult Load(string prefabPath)
        {
            var result = new XUUnityLightMcpPrefabLoadResult();
            var path = (prefabPath ?? "").Trim().Replace('\\', '/');
            if (string.IsNullOrEmpty(path))
            {
                result.Error = XUUnityLightMcpUiTreeBuilder.Diagnostic(
                    "prefab_path_required",
                    "prefabPath is required.");
                return result;
            }

            if (!path.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
            {
                result.Error = XUUnityLightMcpUiTreeBuilder.Diagnostic(
                    "prefab_path_invalid",
                    $"'{path}' is not a .prefab asset path.",
                    "Use a project-relative path such as Assets/UI/Popup.prefab.");
                return result;
            }

            result.NormalizedPath = path;
            result.Guid = AssetDatabase.AssetPathToGUID(path);
            if (string.IsNullOrEmpty(result.Guid))
            {
                result.Error = XUUnityLightMcpUiTreeBuilder.Diagnostic(
                    "prefab_not_found",
                    $"No prefab asset at '{path}'.");
                return result;
            }

            var root = AssetDatabase.LoadAssetAtPath<GameObject>(path);
            if (root == null)
            {
                result.Error = XUUnityLightMcpUiTreeBuilder.Diagnostic(
                    "prefab_not_loadable",
                    $"'{path}' could not be loaded as a GameObject prefab.");
                return result;
            }

            result.Root = root;
            return result;
        }

        public static void Inspect(
            GameObject root,
            bool reportUnassignedReferences,
            XUUnityLightMcpPrefabValidatePayload payload)
        {
            if (root == null)
            {
                return;
            }

            var transforms = root.GetComponentsInChildren<Transform>(true);
            foreach (var transform in transforms)
            {
                if (transform == null)
                {
                    continue;
                }

                payload.inspected_object_count++;
                var objectPath = XUUnityLightMcpUiTreeBuilder.BuildPath(transform);
                InspectGameObject(transform.gameObject, objectPath, reportUnassignedReferences, payload);
            }
        }

        static void InspectGameObject(
            GameObject gameObject,
            string objectPath,
            bool reportUnassignedReferences,
            XUUnityLightMcpPrefabValidatePayload payload)
        {
            if (PrefabUtility.IsPrefabAssetMissing(gameObject))
            {
                payload.defects.Add(new XUUnityLightMcpPrefabDefect
                {
                    defect_type = "missing_prefab_instance",
                    severity = "error",
                    object_path = objectPath,
                    message = "The nested prefab instance points at a prefab asset that no longer exists."
                });
            }

            var components = gameObject.GetComponents<Component>();
            foreach (var component in components)
            {
                payload.inspected_component_count++;
                if (component == null)
                {
                    payload.defects.Add(new XUUnityLightMcpPrefabDefect
                    {
                        defect_type = "missing_script_guid",
                        severity = "error",
                        object_path = objectPath,
                        message = "A component references a script GUID that no longer resolves to a MonoScript."
                    });
                    continue;
                }

                InspectSerializedReferences(component, objectPath, reportUnassignedReferences, payload);
            }
        }

        static void InspectSerializedReferences(
            Component component,
            string objectPath,
            bool reportUnassignedReferences,
            XUUnityLightMcpPrefabValidatePayload payload)
        {
            var componentType = component.GetType().Name;
            using var serializedObject = new SerializedObject(component);
            var property = serializedObject.GetIterator();
            var visited = 0;

            while (property.NextVisible(true))
            {
                if (++visited > MAX_PROPERTIES_PER_COMPONENT)
                {
                    payload.warnings.Add(XUUnityLightMcpUiTreeBuilder.Diagnostic(
                        "prefab_property_scan_truncated",
                        $"'{objectPath}' component '{componentType}' exceeded the per-component property scan bound.",
                        MAX_PROPERTIES_PER_COMPONENT.ToString()));
                    break;
                }

                if (property.propertyType != SerializedPropertyType.ObjectReference)
                {
                    continue;
                }

                if (string.Equals(property.propertyPath, "m_Script", StringComparison.Ordinal))
                {
                    continue;
                }

                payload.inspected_reference_count++;
                var value = property.objectReferenceValue;
                if (value == null)
                {
                    if (property.objectReferenceInstanceIDValue != 0)
                    {
                        payload.defects.Add(new XUUnityLightMcpPrefabDefect
                        {
                            defect_type = "serialized_reference_missing_component",
                            severity = "error",
                            object_path = objectPath,
                            component_type = componentType,
                            property_path = property.propertyPath,
                            expected_type = DeclaredTypeName(property.type),
                            message = "A serialized reference points at an object that no longer exists."
                        });
                    }
                    else if (reportUnassignedReferences)
                    {
                        payload.defects.Add(new XUUnityLightMcpPrefabDefect
                        {
                            defect_type = "serialized_reference_unassigned",
                            severity = "info",
                            object_path = objectPath,
                            component_type = componentType,
                            property_path = property.propertyPath,
                            expected_type = DeclaredTypeName(property.type),
                            message = "A serialized reference is empty. This is legal unless the component requires it."
                        });
                    }

                    continue;
                }

                ClassifyAssignedReference(property, value, objectPath, componentType, payload);
            }
        }

        static void ClassifyAssignedReference(
            SerializedProperty property,
            UnityEngine.Object value,
            string objectPath,
            string componentType,
            XUUnityLightMcpPrefabValidatePayload payload)
        {
            var declared = DeclaredTypeName(property.type);
            if (string.IsNullOrEmpty(declared))
            {
                payload.unverified_reference_count++;
                return;
            }

            var observed = value.GetType();
            if (TypeChainContains(observed, declared))
            {
                return;
            }

            payload.defects.Add(new XUUnityLightMcpPrefabDefect
            {
                defect_type = "serialized_reference_type_mismatch",
                // Only "error" increments errorCount, so a warning here left validation passing for
                // exactly the defect class this validator exists to catch: a reference that
                // deserializes to an incompatible component and throws the moment it is used.
                severity = "error",
                object_path = objectPath,
                component_type = componentType,
                property_path = property.propertyPath,
                expected_type = declared,
                observed_type = observed.Name,
                message = "A serialized reference holds an object whose type is not in the declared field's type chain."
            });
        }

        static bool TypeChainContains(Type type, string declared)
        {
            var current = type;
            while (current != null)
            {
                if (string.Equals(current.Name, declared, StringComparison.Ordinal))
                {
                    return true;
                }

                current = current.BaseType;
            }

            foreach (var contract in type.GetInterfaces())
            {
                if (string.Equals(contract.Name, declared, StringComparison.Ordinal))
                {
                    return true;
                }
            }

            return false;
        }

        public static string DeclaredTypeName(string serializedType)
        {
            var text = serializedType ?? "";
            var open = text.IndexOf('<');
            var close = text.LastIndexOf('>');
            if (open < 0 || close <= open)
            {
                return text;
            }

            return text.Substring(open + 1, close - open - 1).TrimStart('$');
        }

        public static List<string> DistinctDefectTypes(List<XUUnityLightMcpPrefabDefect> defects)
        {
            var types = new List<string>();
            foreach (var defect in defects)
            {
                if (types.Contains(defect.defect_type))
                {
                    continue;
                }

                types.Add(defect.defect_type);
            }

            types.Sort(StringComparer.Ordinal);
            return types;
        }
    }
}
