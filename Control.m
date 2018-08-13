function [P_output1, P_output2, SOC1, SOC2] = Control(P_Required, SOC10, SOC20, gamma_d, Cap)
% This is the control function. Based upon the SOC of the ESS and required
% power, logical steps are taken to calculate the power output of the ESS. 

%% Nomenclature

%% Function Code
Cap1 = Cap(1) ; Cap2 = Cap(2);
if P_Required == 0 % If the required power is zero then the if statement determines whether to try and balance the ESSs. 
    if SOC10 <= 0.55 && SOC10 >= 0.45
        P_output1 = 0; % Since the battery is in an acceptable range its power output is zero
        SOC1 = SOC10;
        if SOC20 < 0.55 && SOC20 > 0.45 % Now the power output of the supercapacitor from the grid is determined. 
            P_output2 = 0;
            
            SOC2 = SOC20;
        elseif SOC20 <= 0.4 && SOC20 >= 0.25 
            P_output2 = -900;
            
            SOC2 = SOC20 - P_output2/(Cap2*3600);
        elseif SOC20 <= 0.8 && SOC20 >= 0.6
            P_output2 = 900;
            
            SOC2 = SOC20 - P_output2/(Cap2*3600);
        else
            P_output2 = 0;
            
            SOC2 = SOC20; 
        end
    elseif SOC10 > 0.55 && SOC10 <= 1
        P_output1 = 900;
        P_output2 = 0;
        SOC1 = SOC10 - (P_output1/3600)/Cap1;
        SOC2 = SOC20;
    elseif SOC10 < 0.45 && SOC10 >=0
        P_output1 = -900;
        P_output2 = 0;
        SOC1 = SOC10 - (P_output1/3600)/Cap1;
        SOC2 = SOC20;
        
    end
elseif (P_Required) ~=0 
    
[P_output1,P_output2, SOC1, SOC2] = PowerCont(P_Required, SOC10, SOC20, gamma_d, Cap);
    
end
    
    
end


 

