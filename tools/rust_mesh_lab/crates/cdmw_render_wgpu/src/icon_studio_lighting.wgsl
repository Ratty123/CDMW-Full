// "Game icon studio": soft boxes around the camera and a lit room, described once
// (the ICON_* constants, written from icon_studio.rs) and read three ways: blurred
// for roughness by a reflection, as irradiance by the diffuse term, and by the
// shadow map through the first box. icon_studio.rs checks these closed forms
// against integrals of the same room.

// Integral over the sphere of exp(sharpness*(cos-1)).
fn icon_lobe_integral(sharpness: f32) -> f32 {
    return 6.28318530718*(1.0-exp(-2.0*sharpness))/sharpness;
}

// Irradiance of a unit lobe on a surface whose normal makes `cosine` with it.
fn icon_lobe_irradiance(cosine: f32, sharpness: f32) -> f32 {
    let eml = exp(-sharpness);
    let em2l = eml*eml;
    let rl = 1.0/sharpness;
    let scale = 1.0+2.0*em2l-rl;
    let bias = (eml-em2l)*rl-em2l;
    let x = sqrt(1.0-scale);
    let x0 = 0.36*cosine;
    let x1 = x/(4.0*0.36);
    let n = x0+x1;
    var y = clamp(cosine,0.0,1.0);
    if abs(x0) <= x1 { y = n*n/x; }
    return (scale*y+bias)*icon_lobe_integral(sharpness);
}

// The studio's axes in world space: camera right, camera up, towards the camera.
// Built from the view direction alone (the orbit camera never rolls), because
// offscreen captures fill in only that part of the camera's basis.
fn icon_studio_axes() -> mat3x3<f32> {
    let towards = safe_normalize(camera.view_direction.xyz,vec3(0.0,0.0,-1.0));
    let right = safe_normalize(cross(vec3(0.0,1.0,0.0),towards),vec3(1.0,0.0,0.0));
    return mat3x3<f32>(right,cross(towards,right),towards);
}

// Camera-relative direction (right, up, towards the camera) of a world direction.
fn icon_studio_frame(direction: vec3<f32>) -> vec3<f32> {
    return direction*icon_studio_axes();
}

// What a reflection along R (studio frame) sees, blurred for the roughness.
// `key` scales the first box: its shadow.
fn icon_studio_reflection(R: vec3<f32>, rough: f32, key: f32) -> vec3<f32> {
    let alpha = max(rough*rough,0.002);
    let kernel = 0.5/(alpha*alpha);
    // tanh overflows to NaN on some drivers long before it reaches 1.
    let slope = 1.0/tanh(min(kernel,12.0))-1.0/kernel;
    var sum = ICON_ROOM_MEAN+ICON_ROOM_SLOPE*R.y*slope;
    var axes = ICON_BOX_AXES;
    var sharpnesses = ICON_BOX_SHARPNESS;
    var radiances = ICON_BOX_RADIANCE;
    for (var i = 0u; i < ICON_BOX_COUNT; i++) {
        let sharpness = sharpnesses[i];
        let blurred = sharpness*kernel/(sharpness+kernel);
        let scale = icon_lobe_integral(sharpness)/icon_lobe_integral(blurred);
        sum += radiances[i]*scale*exp(blurred*(dot(R,axes[i])-1.0))*select(1.0,key,i == 0u);
    }
    return sum;
}

// Irradiance over pi on a surface with normal N (studio frame).
fn icon_studio_irradiance(N: vec3<f32>, key: f32) -> vec3<f32> {
    var sum = ICON_ROOM_MEAN+ICON_ROOM_SLOPE*N.y*(2.0/3.0);
    var axes = ICON_BOX_AXES;
    var sharpnesses = ICON_BOX_SHARPNESS;
    var radiances = ICON_BOX_RADIANCE;
    for (var i = 0u; i < ICON_BOX_COUNT; i++) {
        sum += radiances[i]*icon_lobe_irradiance(dot(N,axes[i]),sharpnesses[i])/3.14159265359
            *select(1.0,key,i == 0u);
    }
    return sum;
}

fn icon_studio_lighting(C: vec3<f32>, N: vec3<f32>, V: vec3<f32>, T: vec3<f32>, rough: f32, metal: f32, spec: f32, occlusion: f32, skin: bool, hair: bool, wet: bool, shadow: f32) -> StudioTerms {
    let normal = icon_studio_frame(N);
    let view = icon_studio_frame(V);
    let NV = clamp(dot(N,V),0.0,1.0);
    let F0 = mix(vec3(0.04*spec),C,metal);
    let brdf = environment_brdf_approx(F0,rough,NV);
    let irradiance = icon_studio_irradiance(normal,shadow);
    let reflection = icon_studio_reflection(reflect(-view,normal),rough,shadow);
    // A cavity hides the room from a rough surface more than from a mirror.
    let cavity = mix(0.4,1.0,occlusion);
    let specular_cavity = mix(cavity,1.0,(1.0-rough)*0.5);
    // A soft box here has no edge: on a mirror-smooth eyeball or pane it would lie
    // as a grey veil over the pupil or the glass instead of a small bright image
    // of a light. Those surfaces take about a third of it.
    var gloss = select(select(1.0,0.45,skin),0.3,hair);
    if wet { gloss = 0.35; }
    var result = StudioTerms(
        C*(1.0-metal)*(vec3(1.0)-environment_brdf_approx(vec3(0.04*spec),rough,NV))*irradiance*cavity,
        reflection*brdf*specular_cavity*gloss);
    let key = safe_normalize(icon_studio_axes()*ICON_BOX_AXES[0],V);
    if skin {
        result.diffuse += C*vec3(0.35,0.12,0.075)*clamp((dot(N,key)+0.35)/1.35,0.0,1.0)*0.35*shadow;
    }
    if hair {
        let H = safe_normalize(V+key,N);
        let alignment = dot(T,H);
        let band = pow(sqrt(clamp(1.0-alignment*alignment,0.0,1.0)),max(4.0,80.0*(1.0-rough)));
        result.specular += C*band*0.22*spec*shadow;
    }
    return result;
}

// Hable's filmic curve (one of the three operators the game's post-process file
// names; its own constants are not in the archives, so these are the published
// ones). Against the ACES fit it does not lift the mid tones, which is what the
// icons show: steel sits near its reflectance times the cloth's light.
fn icon_studio_filmic(x: vec3<f32>) -> vec3<f32> {
    return (x*(0.15*x+vec3(0.05))+vec3(0.004))/(x*(0.15*x+vec3(0.5))+vec3(0.06))-vec3(0.02/0.3);
}

// Exposure, then the curve per channel with white at 11.2: highlights roll off to white.
fn icon_studio_tone(colour: vec3<f32>) -> vec3<f32> {
    let x = max(colour,vec3(0.0))*(2.0*ICON_EXPOSURE);
    return clamp(icon_studio_filmic(x)/icon_studio_filmic(vec3(11.2)),vec3(0.0),vec3(1.0));
}

fn studio_tone(colour: vec3<f32>) -> vec3<f32> {
    if camera.lighting_preset == 4u { return icon_studio_tone(colour); }
    return fixed_studio_tone(colour);
}
