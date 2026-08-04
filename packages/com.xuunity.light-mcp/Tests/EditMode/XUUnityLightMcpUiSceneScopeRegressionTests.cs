using NUnit.Framework;
using UnityEngine;
using XUUnity.LightMcp.Editor.Core;
using XUUnity.LightMcp.Editor.Operations;

namespace XUUnity.LightMcp.Tests.EditMode
{
    [Category("XUUnity.MCP.SelfTest")]
    [Category("XUUnity.MCP.EditMode")]
    [Category("XUUnity.MCP.Fast")]
    [Category("XUUnity.MCP.UiRead")]
    [Category("XUUnity.MCP.SceneScope")]
    public sealed class XUUnityLightMcpUiSceneScopeRegressionTests
    {
        GameObject _canvasRoot;

        [TearDown]
        public void TearDown()
        {
            if (_canvasRoot != null)
            {
                Object.DestroyImmediate(_canvasRoot);
                _canvasRoot = null;
            }
        }

        [Test]
        public void InEditModeAZeroMatchAtTheWidestScopeDoesNotPayASecondTreeWalk()
        {
            // Multi-scene scope needs Play Mode: Edit Mode refuses to add a scene while an untitled scene is
            // unsaved, which is the normal state of a working editor. The runtime cases live in
            // Tests/PlayMode/Ugui/XUUnityLightMcpUiSceneScopePlayModeTests.cs. What is Edit-Mode-specific is the
            // DontDestroyOnLoad status: it can never be `included` here, and requiring that flag to recognise the
            // widest scope made every zero-match query pay a second full tree walk that could not find anything.
            BuildCanvas();

            var payload = RunQuery(
                "{\"targetKind\":\"all_loaded_scenes\",\"includeInactive\":true,"
                + "\"selector\":{\"name\":\"XUUnityMcp_NoSuchNode\"}}");

            Assert.That(payload.match_count, Is.EqualTo(0));
            Assert.That(payload.out_of_scope, Is.False);
            Assert.That(
                payload.target.dont_destroy_on_load_status,
                Is.EqualTo("edit_mode_no_dont_destroy_on_load_scene"));
            Assert.That(
                payload.warnings.Exists(item => item.code == "ui_scope_probe_incomplete"),
                Is.False,
                "the widest reachable scope was already searched, so absence is a real answer");
        }

        [Test]
        public void AZeroMatchTruncatedByTheNodeBudgetDoesNotClaimTheNodeIsNowhere()
        {
            BuildCanvas();

            var payload = RunQuery(
                "{\"targetKind\":\"active_scene\",\"includeInactive\":true,\"maxNodes\":1,"
                + "\"selector\":{\"name\":\"XUUnityMcp_NoSuchNode\"}}");

            Assert.That(payload.match_count, Is.EqualTo(0));
            Assert.That(
                payload.warnings.Exists(item => item.code == "ui_scope_probe_incomplete")
                || payload.errors.Exists(item => item.code == "ui_scope_probe_incomplete"),
                Is.True,
                "a probe stopped by the node budget cannot support \"no node in any loaded scene\"");
        }

        void BuildCanvas()
        {
            _canvasRoot = new GameObject("XUUnityMcp_ScopeCanvas", typeof(RectTransform), typeof(Canvas));
            _canvasRoot.GetComponent<Canvas>().renderMode = RenderMode.ScreenSpaceOverlay;
            _canvasRoot.GetComponent<RectTransform>().sizeDelta = new Vector2(1080f, 1920f);

            var card = new GameObject("Card", typeof(RectTransform));
            card.transform.SetParent(_canvasRoot.transform, false);
            card.GetComponent<RectTransform>().sizeDelta = new Vector2(600f, 400f);
        }

        static XUUnityLightMcpUiQueryPayload RunQuery(string argsJson)
        {
            var response = new XUUnityLightMcpUiQueryOperation().Execute(new XUUnityLightMcpRequest
            {
                request_id = "ui-scene-scope-editmode",
                operation = "unity.ui.query",
                args_json = argsJson
            });
            Assert.That(response.status, Is.EqualTo("ok"));
            return JsonUtility.FromJson<XUUnityLightMcpUiQueryPayload>(response.payload_json);
        }
    }
}
