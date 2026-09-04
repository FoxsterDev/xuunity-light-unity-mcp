using NUnit.Framework;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;
using XUUnity.LightMcp.Editor.Core;
using XUUnity.LightMcp.Editor.Ugui;

namespace XUUnity.LightMcp.Tests.PlayModeUgui
{
    internal sealed class XUUnityLightMcpRaycastIdentityGuardedButton : MonoBehaviour, IPointerClickHandler
    {
        public int accepted;
        public int rejected;
        public GameObject observedRaycastObject;

        public void OnPointerClick(PointerEventData eventData)
        {
            observedRaycastObject = eventData?.pointerCurrentRaycast.gameObject;
            if (observedRaycastObject != gameObject)
            {
                rejected++;
                return;
            }

            accepted++;
            var label = transform.childCount > 0 ? transform.GetChild(0).GetComponent<Text>() : null;
            if (label != null)
            {
                label.text = "Accepted";
            }
        }
    }

    [Category("XUUnity.MCP.SelfTest")]
    [Category("XUUnity.MCP.PlayMode")]
    [Category("XUUnity.MCP.Fast")]
    [Category("XUUnity.MCP.UiInteraction")]
    public sealed class XUUnityLightMcpUiClickRaycastIdentityPlayModeTests
    {
        GameObject _canvasRoot;
        XUUnityLightMcpRaycastIdentityGuardedButton _guarded;

        [SetUp]
        public void SetUp()
        {
            Assert.That(Application.isPlaying, Is.True,
                "raycast identity is a runtime contract and must be proven in PlayMode");

            _canvasRoot = new GameObject("XUUnityMcp_RaycastIdentityCanvas", typeof(RectTransform), typeof(Canvas), typeof(GraphicRaycaster));
            _canvasRoot.GetComponent<Canvas>().renderMode = RenderMode.ScreenSpaceOverlay;
            _canvasRoot.GetComponent<RectTransform>().sizeDelta = new Vector2(1080f, 1920f);

            var button = new GameObject("GuardedButton", typeof(RectTransform), typeof(Image));
            button.transform.SetParent(_canvasRoot.transform, false);
            button.GetComponent<RectTransform>().sizeDelta = new Vector2(400f, 160f);
            _guarded = button.AddComponent<XUUnityLightMcpRaycastIdentityGuardedButton>();

            var label = new GameObject("GuardedLabel", typeof(RectTransform), typeof(Text));
            label.transform.SetParent(button.transform, false);
            label.GetComponent<RectTransform>().sizeDelta = new Vector2(400f, 160f);
            label.GetComponent<Text>().text = "Press";
            label.GetComponent<Text>().raycastTarget = false;
        }

        [TearDown]
        public void TearDown()
        {
            if (_canvasRoot != null)
            {
                Object.DestroyImmediate(_canvasRoot);
                _canvasRoot = null;
            }
            _guarded = null;
        }

        static XUUnityLightMcpUiClickPayload Click(string selectorJson)
        {
            var response = new XUUnityLightMcpUiClickOperation().Execute(new XUUnityLightMcpRequest
            {
                request_id = "ui-click-raycast-identity-selftest",
                operation = XUUnityLightMcpUiClickOperation.RegisteredOperationName,
                args_json = "{\"action\":\"click\",\"approve\":true,\"targetKind\":\"all_loaded_scenes\","
                            + "\"maxNodes\":800,\"maxDepth\":20,\"selector\":" + selectorJson + "}"
            });
            return JsonUtility.FromJson<XUUnityLightMcpUiClickPayload>(response.payload_json);
        }

        [Test]
        public void ClickSatisfiesAHandlerThatValidatesPointerCurrentRaycastIdentity()
        {
            var payload = Click("{\"name\":\"GuardedButton\"}");

            Assert.That(payload.refusal_code, Is.Empty, payload.refusal_code);
            Assert.That(payload.delivered, Is.True, "the guarded handler must receive the pointer event");
            Assert.That(_guarded.rejected, Is.EqualTo(0),
                "a handler comparing pointerCurrentRaycast.gameObject must not reject the delivered click");
            Assert.That(_guarded.accepted, Is.EqualTo(1));
            Assert.That(_guarded.observedRaycastObject, Is.SameAs(_guarded.gameObject),
                "pointerCurrentRaycast must name the GameObject the handler compares against");
            Assert.That(payload.state_changed, Is.True);
            Assert.That(payload.effective, Is.True);
        }

        [Test]
        public void PointerRaycastEvidenceIsAlwaysPublishedAndNamesTheRaycastTarget()
        {
            var payload = Click("{\"name\":\"GuardedButton\"}");

            Assert.That(payload.pointer_raycast_evidence, Is.Not.Empty,
                "every delivered click must say where its pointerCurrentRaycast came from");
            var known = payload.pointer_raycast_evidence == "event_system_raycast_resolves_to_handler"
                        || payload.pointer_raycast_evidence == "synthesized_no_raycast_hit"
                        || payload.pointer_raycast_evidence == "synthesized_no_event_system";
            Assert.That(known, Is.True,
                $"unknown pointer raycast evidence value '{payload.pointer_raycast_evidence}'");
            Assert.That(payload.pointer_raycast_target_path, Does.EndWith("GuardedButton"));
            Assert.That(payload.occluded_by_path, Is.Empty);

            var synthesized = payload.pointer_raycast_evidence.StartsWith("synthesized");
            var warned = payload.warnings.Exists(w => w.code == "ui_click_pointer_raycast_synthesized");
            Assert.That(warned, Is.EqualTo(synthesized),
                "a synthesized raycast must warn, and an observed one must not");
        }

        [Test]
        public void ClickOnANonRaycastChildStillNamesTheHandlerAsTheRaycastTarget()
        {
            var payload = Click("{\"name\":\"GuardedLabel\"}");

            Assert.That(payload.refusal_code, Is.Empty, payload.refusal_code);
            Assert.That(payload.delivered_to_path, Does.EndWith("GuardedButton"),
                "the click must resolve up to the ancestor handler");
            Assert.That(_guarded.rejected, Is.EqualTo(0),
                "targeting a non-raycast child must not produce a raycast identity the handler rejects");
            Assert.That(_guarded.accepted, Is.EqualTo(1));
        }

        [Test]
        public void AnOccludingHandlerIsRefusedInsteadOfClickedThrough()
        {
            var blocker = new GameObject("OccludingOverlay", typeof(RectTransform), typeof(Image));
            blocker.transform.SetParent(_canvasRoot.transform, false);
            blocker.GetComponent<RectTransform>().sizeDelta = new Vector2(1080f, 1920f);
            blocker.AddComponent<XUUnityLightMcpRaycastIdentityGuardedButton>();
            blocker.transform.SetAsLastSibling();

            var payload = Click("{\"name\":\"GuardedButton\"}");

            if (payload.pointer_raycast_hit_count == 0)
            {
                Assert.Ignore("this runtime produced no event-system raycast hit, so occlusion cannot be observed here");
            }

            Assert.That(payload.refusal_code, Is.EqualTo("ui_target_occluded"), payload.pointer_raycast_evidence);
            Assert.That(payload.delivered, Is.False);
            Assert.That(payload.occluded_by_path, Does.EndWith("OccludingOverlay"));
            Assert.That(_guarded.accepted, Is.EqualTo(0));
        }
    }
}
