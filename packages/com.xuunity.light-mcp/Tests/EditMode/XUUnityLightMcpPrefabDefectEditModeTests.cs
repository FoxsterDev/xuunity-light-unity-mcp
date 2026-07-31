using System.IO;
using System.Text.RegularExpressions;
using NUnit.Framework;
using UnityEditor;
using UnityEngine;
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
            InjectUnresolvableScriptGuid();

            var payload = RunValidate();

            Assert.That(
                payload.passed,
                Is.False,
                "an unresolvable script GUID leaves a missing component and must fail before PlayMode");
            CollectionAssert.Contains(payload.defect_types, "missing_script_guid");
            Assert.That(payload.status, Is.EqualTo("failed"));
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

        XUUnityLightMcpPrefabValidatePayload RunValidate()
        {
            var response = new XUUnityLightMcpPrefabValidateOperation().Execute(new XUUnityLightMcpRequest
            {
                request_id = "prefab-defect-selftest",
                operation = "unity.prefab.validate",
                args_json = "{\"prefabPath\":\"" + _prefabPath + "\"}"
            });
            Assert.That(response.status, Is.EqualTo("ok"));
            return JsonUtility.FromJson<XUUnityLightMcpPrefabValidatePayload>(response.payload_json);
        }
    }
}
