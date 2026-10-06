import Foundation
import Vision
import AppKit

// usage: facebox <image>...  → JSON {path: [[x,y,w,h,kind],...]} (0~1 비율, 원점 = 왼쪽 위; kind 1=얼굴 0=주목 물체)
// 얼굴이 있으면 얼굴 사각형들, 없으면 주목도(objectness saliency)가 가장 큰 물체의 사각형 하나.
var out: [String: [[Double]]] = [:]
for p in CommandLine.arguments.dropFirst() {
    guard let img = NSImage(contentsOfFile: p),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { out[p] = []; continue }
    let h = VNImageRequestHandler(cgImage: cg, options: [:])
    let faceReq = VNDetectFaceRectanglesRequest()
    try? h.perform([faceReq])
    var rects: [[Double]] = []
    for r in (faceReq.results ?? []) {
        let b = r.boundingBox  // 원점 = 왼쪽 아래
        rects.append([Double(b.minX), Double(1 - b.maxY), Double(b.width), Double(b.height), 1.0])
    }
    if rects.isEmpty {
        let salReq = VNGenerateObjectnessBasedSaliencyImageRequest()
        try? h.perform([salReq])
        if let obs = salReq.results?.first as? VNSaliencyImageObservation,
           let objs = obs.salientObjects, !objs.isEmpty {
            let best = objs.max(by: { $0.boundingBox.width * $0.boundingBox.height < $1.boundingBox.width * $1.boundingBox.height })!
            let b = best.boundingBox
            rects.append([Double(b.minX), Double(1 - b.maxY), Double(b.width), Double(b.height), 0.0])
        }
    }
    out[p] = rects
}
let data = try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
