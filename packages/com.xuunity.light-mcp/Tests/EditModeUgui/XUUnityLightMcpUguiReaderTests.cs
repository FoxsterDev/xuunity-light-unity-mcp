using NUnit.Framework;
using UnityEngine;
using UnityEngine.UI;
using XUUnity.LightMcp.Editor.Core;
using XUUnity.LightMcp.Editor.Operations;

namespace XUUnity.LightMcp.Tests.EditModeUgui
{
    [Category("XUUnity.MCP.SelfTest")]
    [Category("XUUnity.MCP.EditMode")]
    [Category("XUUnity.MCP.Fast")]
    [Category("XUUnity.MCP.UiReadUgui")]
    public sealed class XUUnityLightMcpUguiReaderTests
    {
        GameObject _canvasRoot;

        [SetUp]
        public void SetUp()
        {
            _canvasRoot = new GameObject("XUUnityMcp_UguiCanvas", typeof(RectTransform), typeof(Canvas));
            _canvasRoot.GetComponent<Canvas>().renderMode = RenderMode.ScreenSpaceOverlay;
            _canvasRoot.GetComponent<RectTransform>().sizeDelta = new Vector2(1080f, 1920f);

            var title = NewChild("Title");
            var label = title.AddComponent<Text>();
            label.text = "Daily Gift";

            var button = NewChild("ClaimButton");
            button.AddComponent<Image>();
            var claim = button.AddComponent<Button>();
            claim.interactable = false;

            var invisible = NewChild("InvisibleLabel");
            var invisibleText = invisible.AddComponent<Text>();
            invisibleText.text = "Hidden copy";
            invisibleText.color = new Color(1f, 1f, 1f, 0f);
        }

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
        public void Reader_IsRegisteredAndReportedInTheSnapshot()
        {
            var payload = RunTree();

            CollectionAssert.Contains(payload.component_detail_backends, "ugui");
            Assert.That(payload.proof_class, Is.EqualTo("semantic_ui_tree"));
            Assert.That(
                payload.warnings.Exists(item => item.code == "ui_component_details_unavailable"),
                Is.False);
            Assert.That(payload.screen_width, Is.EqualTo(payload.target.screen_width));
            Assert.That(payload.screen_height, Is.EqualTo(payload.target.screen_height));
            Assert.That(payload.render_width, Is.EqualTo(payload.target.render_width));
            Assert.That(payload.render_height, Is.EqualTo(payload.target.render_height));
            Assert.That(payload.render_target_available, Is.EqualTo(payload.target.render_target_available));
            Assert.That(payload.render_target_differs_from_screen,
                Is.EqualTo(payload.target.render_target_differs_from_screen));
            Assert.That(payload.playmode_loop_liveness, Is.EqualTo("not_playing"));
            Assert.That(payload.result_trust_class, Is.EqualTo("editor_truth_confirmed"));
        }

        [Test]
        public void Reader_ExtractsTextAndResolvedFont()
        {
            var payload = RunTree();
            var title = payload.nodes.Find(node => node.name == "Title");

            Assert.That(title, Is.Not.Null);
            Assert.That(title.has_text, Is.True);
            Assert.That(title.text, Is.EqualTo("Daily Gift"));
            Assert.That(title.text_source, Is.EqualTo("UnityEngine.UI.Text"));
            Assert.That(title.font_resolved_status, Is.EqualTo("resolved"));
            Assert.That(title.material_resolved_status, Is.EqualTo("resolved"));
        }

        [Test]
        public void Reader_ReportsNonInteractableSelectable()
        {
            var payload = RunTree();
            var button = payload.nodes.Find(node => node.name == "ClaimButton");

            Assert.That(button, Is.Not.Null);
            Assert.That(button.interactable_known, Is.True);
            Assert.That(button.interactable, Is.False);
            Assert.That(button.raycast_target_known, Is.True);
        }

        [Test]
        public void Reader_TreatsFullyTransparentGraphicAsInvisible()
        {
            var payload = RunTree();
            var invisible = payload.nodes.Find(node => node.name == "InvisibleLabel");

            Assert.That(invisible, Is.Not.Null);
            Assert.That(invisible.active_in_hierarchy, Is.True);
            Assert.That(invisible.effective_alpha, Is.EqualTo(0f).Within(0.001f));
            Assert.That(invisible.visible, Is.False, "alpha-0 text is rendered but not visible");
        }

        [Test]
        public void GetText_ReturnsTheSemanticStringForAUniqueSelector()
        {
            var response = new XUUnityLightMcpUiGetTextOperation().Execute(new XUUnityLightMcpRequest
            {
                request_id = "ugui-get-text-selftest",
                operation = "unity.ui.get_text",
                args_json = "{\"selector\":{\"name\":\"Title\"}}"
            });
            var payload = JsonUtility.FromJson<XUUnityLightMcpUiQueryPayload>(response.payload_json);

            Assert.That(payload.success, Is.True, string.Join("; ", payload.errors.ConvertAll(item => item.code)));
            Assert.That(payload.has_text, Is.True);
            Assert.That(payload.text, Is.EqualTo("Daily Gift"));
            Assert.That(payload.screen_width, Is.EqualTo(payload.target.screen_width));
            Assert.That(payload.render_width, Is.EqualTo(payload.target.render_width));
            Assert.That(payload.playmode_loop_liveness, Is.EqualTo("not_playing"));
        }

        [Test]
        public void Query_MatchesOnTextAndInteractability()
        {
            var byText = RunQuery("{\"selector\":{\"textContains\":\"Gift\"}}");
            var interactableOnly = RunQuery("{\"selector\":{\"type\":\"Button\",\"requireInteractable\":true}}");

            Assert.That(byText.match_count, Is.EqualTo(1));
            Assert.That(byText.matches[0].name, Is.EqualTo("Title"));
            Assert.That(
                interactableOnly.match_count,
                Is.Zero,
                "the only Button is non-interactable, so requireInteractable must exclude it");
        }

        GameObject NewChild(string name)
        {
            var child = new GameObject(name, typeof(RectTransform));
            child.transform.SetParent(_canvasRoot.transform, false);
            child.GetComponent<RectTransform>().sizeDelta = new Vector2(400f, 100f);
            return child;
        }

        static XUUnityLightMcpUiTreePayload RunTree()
        {
            var response = new XUUnityLightMcpUiTreeSnapshotOperation().Execute(new XUUnityLightMcpRequest
            {
                request_id = "ugui-tree-selftest",
                operation = "unity.ui.tree_snapshot",
                args_json = "{\"targetKind\":\"active_scene\",\"includeInactive\":true}"
            });
            return JsonUtility.FromJson<XUUnityLightMcpUiTreePayload>(response.payload_json);
        }

        static XUUnityLightMcpUiQueryPayload RunQuery(string argsJson)
        {
            var response = new XUUnityLightMcpUiQueryOperation().Execute(new XUUnityLightMcpRequest
            {
                request_id = "ugui-query-selftest",
                operation = "unity.ui.query",
                args_json = argsJson
            });
            return JsonUtility.FromJson<XUUnityLightMcpUiQueryPayload>(response.payload_json);
        }
    }
}
