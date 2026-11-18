struct StudioTerms { diffuse: vec3<f32>, specular: vec3<f32>, };

// The three lights' strength on every surface, and the room's fill on the
// diffuse of non-metals: set against the game's item icons so dark cloth, fur
// and leather read at the icons' lightness without a pale veil over colour.
const STUDIO_LIGHT_GAIN: f32 = 1.3;
const STUDIO_FILL_GAIN: f32 = 1.8;
// How brightly the lit walls show in a metal reflection.
const STUDIO_METAL_ROOM_GAIN: f32 = 1.8;

fn fixed_studio_brdf(C: vec3<f32>, N: vec3<f32>, V: vec3<f32>, L: vec3<f32>, rough: f32, metal: f32, spec: f32, skin: bool) -> StudioTerms {
    let H = safe_normalize(V+L,N);
    let NV = max(dot(N,V),0.001);
    let NL = clamp(dot(N,L),0.0,1.0);
    let NH = clamp(dot(N,H),0.0,1.0);
    let VH = clamp(dot(V,H),0.0,1.0);
    let a = rough*rough;
    let a2 = a*a;
    let d = NH*NH*(a2-1.0)+1.0;
    let D = a2/(3.14159265359*d*d+1e-7);
    let Gv = NL*sqrt(NV*NV*(1.0-a2)+a2);
    let Gl = NV*sqrt(NL*NL*(1.0-a2)+a2);
    let visibility = 0.5/max(Gv+Gl,1e-5);
    let F0 = mix(vec3(0.04*spec),C,metal);
    var Fr = F0+(vec3(1.0)-F0)*pow(1.0-VH,5.0);
    if skin { Fr = F0+(Fr-F0)*0.35; }
    return StudioTerms((vec3(1.0)-Fr)*(1.0-metal)*C/3.14159265359*NL,
        D*visibility*Fr*select(1.0,0.6,skin)*NL);
}

fn fixed_studio_lighting(C: vec3<f32>, N: vec3<f32>, V: vec3<f32>, T: vec3<f32>, rough: f32, metal: f32, spec: f32, occlusion: f32, skin: bool, hair: bool, shadow: f32) -> StudioTerms {
    let key = normalize(vec3(-0.45,0.8,-0.55));
    let directions = array<vec3<f32>,3>(key,normalize(vec3(0.6,0.25,0.4)),normalize(vec3(0.2,0.65,0.7)));
    let colours = array<vec3<f32>,3>(vec3(1.0,0.96,0.91)*3.0*shadow,vec3(0.60,0.72,0.92)*0.8,vec3(0.9,0.79,0.68)*1.1);
    var result = StudioTerms(vec3(0.0),vec3(0.0));
    for (var i = 0u; i < 3u; i++) {
        let light = fixed_studio_brdf(C,N,V,directions[i],rough,metal,spec,skin);
        result.diffuse += light.diffuse*colours[i]*STUDIO_LIGHT_GAIN;
        // Hair, fur and feather cards take their highlight from the strand band
        // below; a light's own white highlight on a card greys a saturated dye.
        result.specular += light.specular*colours[i]*STUDIO_LIGHT_GAIN*select(1.0,0.3,hair);
    }
    let sky = clamp(N.y*0.5+0.5,0.0,1.0);
    let ambient = mix(vec3(0.20,0.18,0.16),vec3(0.55,0.62,0.73),sky);
    let F0 = mix(vec3(0.04*spec),C,metal);
    let R = reflect(-V,N);
    // A reflection sees the room the ambient term describes, and its walls lit
    // by the three lights (their summed colour, 80% reflective, spread over the
    // sphere). A mirror-like conductor has no diffuse term, so this is all the
    // colour its unlit parts have; the dimmer, bluer sky alone drew steel navy.
    // Only for the metal fraction: dielectrics keep the reflection they had.
    let up = clamp(R.y*0.5+0.5,0.0,1.0);
    var refl = mix(
        mix(vec3(0.13,0.12,0.11),vec3(0.40,0.46,0.56),up),
        mix(vec3(0.20,0.18,0.16),vec3(0.55,0.62,0.73),up)+vec3(0.285,0.275,0.268)*STUDIO_METAL_ROOM_GAIN,
        clamp(metal,0.0,1.0));
    let blur = max(rough*rough,0.03);
    let lobe = pow(clamp(dot(R,normalize(vec3(-0.4,0.8,-0.6))),0.0,1.0),2.0/max(blur,0.02));
    refl += lobe*vec3(2.4,2.25,2.05)*(1.0-rough*0.6);
    let NV = clamp(dot(N,V),0.0,1.0);
    // A rough dielectric does not mirror the room at a grazing angle: its share of
    // a reflection is the split-sum reflectance, which stays near F0 when rough.
    // The old grazing term rose to 1 - roughness there, and drew a grey-white
    // sheen on feather and hair cards. The metal fraction keeps that term.
    let grazing = mix(F0,max(vec3(1.0-rough),F0),pow(1.0-NV,5.0))*(1.0-rough*0.35);
    let environment_specular = refl*mix(environment_brdf_approx(vec3(0.04*spec),rough,NV),grazing,clamp(metal,0.0,1.0));
    let env_scale = 0.7*mix(0.4,1.0,occlusion);
    result.diffuse += C*(1.0-metal)*ambient*env_scale*STUDIO_FILL_GAIN;
    // Hair, fur and feather cards take their highlight from the strand band below;
    // the white reflection of the room would grey a saturated dye.
    result.specular += environment_specular*select(1.0,0.3,skin || hair)*env_scale;
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

fn fixed_studio_tone(colour: vec3<f32>) -> vec3<f32> {
    let C = max(colour,vec3(0.0));
    let peak = max(C.r,max(C.g,C.b));
    if peak <= 0.76 { return C; }
    return C*((1.0-0.24*0.24/(peak+0.24-0.76))/peak);
}
