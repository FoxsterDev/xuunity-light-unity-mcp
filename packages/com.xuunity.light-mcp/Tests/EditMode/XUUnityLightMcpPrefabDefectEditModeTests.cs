using System.IO;
using System.Text.RegularExpressions;
using NUnit.Framework;
using UnityEditor;
using UnityEngine;
using UnityEngine.TestTools;
using XUUnity.LightMcp.Editor.Core;
using XUUnity.LightMcp.Editor.Operations;

namespace XUUnity.LightMcp.Tests.EditMode
{
    /// <summary>
    /// The defect class that motivated the whole reference-driven UI effort: a prefab whose script
    /// GUID no longer resolves, producing a missing component and a null reference the moment a
    /// presenter subscribes to it. Compilation cannot see it, and until now no test emitted it —
    /// the only coverage was a source grep for the defect-type string, which passes even if the
    /// branch is dead.
    /// </summary>
    [Category("XUUnity.MCP.SelfTest")]
    [Category("XUUnity.MCP.EditMode")]
    [Category("XUUnity.MCP.Fast")]
    [Category("XUUnity.MCP.PrefabDefects")]
    public sealed class XUUnityLightMcpPrefabDefectEditModeTests
    {
        const string GENERATED_ROOT = "Assets/XUUnityLightMcpGenerated";
        const string PREFAB_DIR = GENERATED_ROOT + "/DefectSelfTest";

        string _prefabPath = "";

        [SetUp]
        public void SetUp()
        {
            Directory.CreateDirectory(PREFAB_DIR);
            AssetDatabase.Refresh();

            var root = new GameObject("XUUnityMcp_DefectRoot", typeof(RectTransform));
            var child = new GameObject("CloseButton", typeof(RectTransform));
            child.transform.SetParent(root.transform, false);

            _prefabPath = PREFAB_DIR + "/XUUnityMcp_DefectRoot.prefab";
            PrefabUtility.SaveAsPrefabAsset(root, _prefabPath);
            Object.DestroyImmediate(root);
            AssetDatabase.Refresh();
        }

        [TearDown]
        public void TearDown()
        {
            if (!string.IsNullOrEmpty(_prefabPath))
            {
                AssetDatabase.DeleteAsset(_prefabPath);
                AssetDatabase.DeleteAsset(PREFAB_DIR);
                _prefabPath = "";
            }
            AssetDatabase.Refresh();
            LogAssert.ignoreFailingMessages = false;
        }

        [Test]
        public void Validate_PassesForAHealthyPrefab()
        {
            var payload = RunValidate();

            Assert.That(payload.passed, Is.True, "a prefab with no defects must validate");
            CollectionAssert.IsEmpty(payload.defect_types);
        }

        [Test]
        public void Validate_FailsWhenAScriptGuidNoLongerResolves()
        {
            // Importing a deliberately broken prefab logs an import error, and the test framework
            // fails a test on any unhandled error log. The broken import is the point of the test.
            LogAssert.ignoreFailingMessages = true;
            InjectUnresolvableScriptGuid();

            var payload = RunValidate();

            Assert.That(
                payload.passed,
                Is.False,
                "an unresolvable script GUID leaves a missing component and must fail before PlayMode");
            CollectionAssert.Contains(payload.defect_types, "missing_script_guid");
            Assert.That(payload.status, Is.EqualTo("failed"));
        }

        [Test]
        public void Validate_ScopesTheUnassignedReferenceReportAwayFromEngineDefaults()
        {
            // Every empty optional field on a built-in component is legal and normal, so an unscoped
            // report buries the one finding an operator cares about: an unfilled project [SerializeField].
            var scoped = RunValidate("\"reportUnassignedReferences\":true");
            var all = RunValidate("\"reportUnassignedReferences\":true,\"unassignedReferenceScope\":\"all\"");

            Assert.That(scoped.unassigned_reference_scope, Is.EqualTo("project_scripts"));
            Assert.That(all.unassigned_reference_scope, Is.EqualTo("all"));
            Assert.That(
                all.unassigned_reference_count,
                Is.EqualTo(scoped.unassigned_reference_count),
                "the scope must change what is reported, never what is inspected");
            Assert.That(
                scoped.unassigned_reference_suppressed_count,
                Is.EqualTo(scoped.unassigned_reference_count),
                "this probe prefab carries only engine components, so every empty field is out of scope");
            Assert.That(CountUnassigned(all), Is.GreaterThanOrEqualTo(CountUnassigned(scoped)));
            Assert.That(CountUnassigned(scoped), Is.Zero);
        }

        [Test]
        public void Validate_DoesNotReportUnassignedReferencesUnlessAsked()
        {
            var payload = RunValidate();

            Assert.That(payload.unassigned_reference_scope, Is.EqualTo("not_reported"));
            Assert.That(payload.unassigned_reference_count, Is.Zero);
        }

        static int CountUnassigned(XUUnityLightMcpPrefabValidatePayload payload)
        {
            return payload.defects.FindAll(
                defect => defect.defect_type == "serialized_reference_unassigned").Count;
        }

        /// <summary>
        /// Rewrites the child's component reference to a GUID no asset owns, which is what an
        /// obsolete or moved script leaves behind in a serialized prefab.
        /// </summary>
        void InjectUnresolvableScriptGuid()
        {
            var absolute = Path.GetFullPath(_prefabPath);
            var text = File.ReadAllText(absolute);

            // Append a component whose script GUID cannot resolve, attached to the CloseButton
            // file id if one is present, otherwise to the document as an orphan MonoBehaviour.
            var fileIdMatch = Regex.Match(text, @"--- !u!1 &(\d+)\r?\nGameObject:");
            var owner = fileIdMatch.Success ? fileIdMatch.Groups[1].Value : "100000";
            text +=
                "--- !u!114 &114999999999999999\n"
                + "MonoBehaviour:\n"
                + "  m_ObjectHideFlags: 0\n"
                + "  m_CorrespondingSourceObject: {fileID: 0}\n"
                + "  m_PrefabInstance: {fileID: 0}\n"
                + "  m_PrefabAsset: {fileID: 0}\n"
                + "  m_GameObject: {fileID: " + owner + "}\n"
                + "  m_Enabled: 1\n"
                + "  m_EditorHideFlags: 0\n"
                + "  m_Script: {fileID: 11500000, guid: ffffffffffffffffffffffffffffffff, type: 3}\n"
                + "  m_Name: \n"
                + "  m_EditorClassIdentifier: \n";
            File.WriteAllText(absolute, text);
            AssetDatabase.ImportAsset(_prefabPath, ImportAssetOptions.ForceUpdate);
            AssetDatabase.Refresh();
        }

        XUUnityLightMcpPrefabValidatePayload RunValidate(string extraArgsJson = "")
        {
            var response = new XUUnityLightMcpPrefabValidateOperation().Execute(new XUUnityLightMcpRequest
            {
                request_id = "prefab-defect-selftest",
                operation = "unity.prefab.validate",
                args_json = "{\"prefabPath\":\"" + _prefabPath + "\""
                            + (string.IsNullOrEmpty(extraArgsJson) ? "" : "," + extraArgsJson) + "}"
            });
            Assert.That(response.status, Is.EqualTo("ok"));
            return JsonUtility.FromJson<XUUnityLightMcpPrefabValidatePayload>(response.payload_json);
        }
    }
}
