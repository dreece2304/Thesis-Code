function [P_output1, P_output2, SOC1, SOC2,b] = Control(P_Required, SOC10, SOC20,  Cap, gamma_d)
% This is the control function. Based upon the SOC of the ESS and required
% power, logical steps are taken to calculate the power output of the ESS. 

%% Nomenclature

%% Function Code
SC_lim = Cap(3); 
P2 = 0.1*Cap(2);
% The capacity of each ESS is extracted from the capacity vector. 
Cap1 = Cap(1) ; Cap2 = Cap(2);
% The potential SOC of each ESS is calculated if it were to output all of
% P_Required. This determines whether there is enough SOC. 

SOC1ex = SOC10 - (P_Required/(gamma_d*3600))/Cap1; 
SOC2ex = SOC20 - (P_Required/3600)/Cap2;

if P_Required == 0 % If the required power is zero then the if statement determines whether to try and balance the ESSs. 
    b1 = 0;
    b2 = 0;
    if SOC10 <= 0.6 && SOC10 >= 0.4
        %if there is power taken from grid here there is an equivalent
        %cost
        P_output1 = 0; % Since the battery is in an acceptable range its power output is zero

        if SOC20 < 0.8 && SOC20 > 0 % Now the power output of the supercapacitor from the grid is determined. 
            P_output2 = 0;
            

        elseif SOC20 <= 0.8 && SOC20 >= 0 
            P_output2 = -P2;
            
            %CfG = 0 ; % Cost from grid in $/

        elseif SOC20 <= 1 && SOC20 >= 0.8
            P_output2 = P2;  
        elseif isnan(SOC20) == 1
            P_output2 = 0;
 
        end
    elseif SOC10 > 0.6 && SOC10 <= 1
        P_output1 = 0.5; % This allows the battery to output 10%  of its power rating to try and balance
        
        if SOC20 < 0.8 && SOC20 > 0.2 % Now the power output of the supercapacitor from the grid is determined. 
            P_output2 = 0;
           

        elseif SOC20 <= 0.2 && SOC20 >= 0 
            P_output2 = -P2;
            
            %CfG = 0 ; % Cost from grid in $/

        elseif SOC20 <= 1 && SOC20 >= 0.8
            P_output2 = P2;
        elseif isnan(SOC20) == 1
            P_output2 = 0;            
            
        end

    elseif SOC10 < 0.4 && SOC10 >=0
        P_output1 = -0.5;
        if SOC20 < 0.8 && SOC20 > 0.2 % Now the power output of the supercapacitor from the grid is determined. 
            P_output2 = 0;            
        elseif SOC20 <= 0.2 && SOC20 >= 0 
            P_output2 = -P2;
            %CfG = 0 ; % Cost from grid in $/
        elseif SOC20 <= 1 && SOC20 >= 0.80
            P_output2 = P2;
        elseif isnan(SOC20) == 1
            P_output2 = 0; 
        end    
    end
elseif abs(P_Required) >= SC_lim
    b1 = 1; b2 = 1;
    if SOC2ex >= 0 && SOC2ex <= 1
       P_output2 = P_Required;
       P_output1 = 0;
    elseif SOC2ex < 0 || SOC2ex > 1 || isnan(SOC2ex) == 1
        P_output2 = 0;
        if SOC1ex >= 0.2 && SOC1ex <= 0.8
            P_output1 = P_Required;
        elseif SOC1ex < 0.2 || SOC1ex > 0.8
            P_output1 = 0;
        end
    end
elseif abs(P_Required) < SC_lim && P_Required ~= 0
    b1 = 1 ;b2 = 1;
       if SOC1ex >= 0.2 && SOC1ex <= 0.8
           P_output1 = P_Required;
           P_output2 = 0;
       elseif SOC1ex < 0.2 || SOC1ex > 0.8 
           P_output1 = 0;
           if SOC2ex >= 0 && SOC2ex <= 1
               P_output2 = P_Required;
               P_output1 = 0;
           elseif SOC2ex < 0 || SOC2ex > 1 || isnan(SOC2ex) == 1
               P_output2 = 0;
               P_output1 = 0;
           end
       end
end
b = [b1 b2];   
SOC1 = SOC10 - (P_output1/(gamma_d*3600))/Cap1; 
SOC2 = SOC20 - (P_output2/3600)/Cap2;   
end


 

